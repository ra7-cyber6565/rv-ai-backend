# PR #81 acceptance

This repair branch is not complete merely because CI is green.

Required acceptance invariants:

- Technical Python/Pine/backtest `script` requests must not enter creative dialogue coverage.
- Trading hypothesis structure may normalize only details explicitly present in prose; it must not invent thresholds or results.
- A `specialist_handoff` failure may recover only through bounded retry/fallback. If recovery is not observed, the run must remain PARTIAL and name the missing reasoning pass.
- Final trading-model acceptance requires the requested model/testing deliverables and must not depend on irrelevant creative coverage.
- No fabricated backtest, paid-provider fallback, or unsupported COMPLETE claim.

## Live acceptance binding

The generic hosted COMPANY/COMPANY_PLUS live gate uses a fixed superconductivity question, so by itself it does **not** prove the trading-specific repairs in this PR.

PR #81 therefore adds `scripts/run_pr81_trading_live_acceptance.py`, a fixed non-arbitrary `MAXIMUM` trading question that exercises the normal public `AgentManager` path. Its sanitized evaluator requires:

- technical `script` intent stays outside CRAFT/dialogue;
- trading final-acceptance contract is active and recognizes a Python technical-script deliverable;
- the requested Python backtest script is actually delivered;
- relevant model/baseline/leakage/cost/OOS contract points are registered;
- numeric-threshold provenance runs and any unsupported threshold fails closed to PARTIAL;
- missing requested empirical/model deliverables can never coexist with public COMPLETE;
- unified Max actually executes six specialist drafts when the confirmed-free model layer is available;
- a prepared, untruncated specialist handoff consumed by analysis or synthesis cannot remain a missing pass.

The evaluator stores only structural booleans/counters and an answer SHA-256. It does not persist the question, answer, source text, provider body, or credentials.

The existing opt-in hosted workflow now runs this Max trading lane **only after** the COMPANY and COMPANY_PLUS live prerequisites pass, avoiding another six-worker allocation after an earlier live failure.

Exact-head CI **and** a fresh hosted live workflow-dispatch receipt containing a passing `trading_max` section are required before this PR can leave draft status. A skipped live step, an older SHA receipt, or a superconductivity-only receipt is not acceptance evidence.
