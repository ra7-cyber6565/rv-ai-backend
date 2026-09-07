# Unified Max Mode Contract

This file is a permanent product/runtime contract for future coding agents.

## Public product surface

The normal public app has exactly two research choices:

1. `Chat` -> backend `QUICK`.
2. `Max` -> backend `MAXIMUM`.

`DEEP`, `MARATHON`, `COMPANY`, `COMPANY_PLUS`, and `CUSTOM` may remain accepted backend names for backward compatibility, focused tests, or admin/developer use. They are not separate decisions the normal user should have to make.

## What Max means

`MAXIMUM` is the unified bounded super-orchestrator, not merely the old three-round Max preset.

It must inherit the strongest useful rails already built in this repository:

- Marathon-style full configured research rounds.
- Papers, books, datasets, patents when the question makes them relevant.
- Legally accessible full-text reading within the configured budget.
- Counter-evidence / red-team work.
- Six specialist first-pass workers plus chief synthesis.
- The first four specialist roles are exactly the original Company core: `evidence`, `validation`, `mechanism`, `red_team`.
- The two additional Company+ roles are `data_quality` and `implementation`.
- AI-1 evidence/research governance and AI-2 validation remain downstream in the normal `AgentManager` research path.
- Existing hypothesis, experiment/simulation, trading-model, physics, document, evidence, contradiction, verification, and synthesis lanes remain available to the same Max run when their applicability gates say they are relevant.

## No pointless duplication

Do not run a separate four-worker Company pass and then the six-worker Company+ pass on the same evidence merely to claim that both modes were used. `ROLES[:6]` already contains `ROLES[:4]`; duplicating those workers burns quota without adding an independent capability.

The requirement is capability inclusion, not duplicate execution of weaker subsets.

## Relevance gating is required

"Use everything" means every useful capability is available to Max and no capability is skipped because the user chose the wrong legacy mode. It does not mean running irrelevant tools blindly.

Examples:

- A trading-model request should activate trading/model validation, leakage/friction/OOS/backtest or simulation lanes when executable evidence is available.
- A physics question should use physics/experiment/quantitative validation lanes when applicable.
- Uploaded books/PDFs should be read through the document/full-text lanes while external discovery remains available.
- A simple factual research question does not need a fake trading backtest just to tick a box.

## Truth and budget rules remain mandatory

Max is strongest available research, not unlimited internet, guaranteed truth, guaranteed profit, or permission to fabricate tests.

- Confirmed-zero-cost routing remains mandatory unless the project policy is explicitly changed by the user.
- Missing provider quota, evidence, executable data, or required receipts must remain `PARTIAL`, `INCONCLUSIVE`, `UNKNOWN`, `NOT TESTED`, or the existing truthful equivalent.
- A proposed test is not a performed test.
- A literature claim is not an app experiment result.
- Six worker drafts are not independent scientific replication.

## Change rule

Any future change that exposes legacy modes as separate normal-user buttons, weakens `MAXIMUM` below the strongest bounded integrated configuration, or bypasses the existing AI-1/AI-2 truth gates violates this contract unless the user explicitly requests that product change.
