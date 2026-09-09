# PR #81 acceptance

This repair branch is not complete merely because CI is green.

Required acceptance invariants:

- Technical Python/Pine/backtest `script` requests must not enter creative dialogue coverage.
- Trading hypothesis structure may normalize only details explicitly present in prose; it must not invent thresholds or results.
- A `specialist_handoff` failure may recover only through bounded retry/fallback. If recovery is not observed, the run must remain PARTIAL and name the missing reasoning pass.
- Final trading-model acceptance requires the requested model/testing deliverables and must not depend on irrelevant creative coverage.
- No fabricated backtest, paid-provider fallback, or unsupported COMPLETE claim.

Exact-head CI and a new live acceptance run are required before this PR can leave draft status.
