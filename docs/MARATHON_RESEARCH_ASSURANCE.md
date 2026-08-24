# MARATHON research assurance

`MARATHON` is the longest bounded research preset. It prioritises legally
accessible evidence and auditability over response speed.

## What the preset does

- Runs all 5 configured discovery rounds; credible early evidence does not stop
  later source-derived author/work, cross-domain and counter-evidence searches.
- Keeps the run bounded: 40 ranked sources, 16 legally accessible full-text
  attempts, 6 results per connector, 360 seconds of discovery budget per round
  and 4 zero-cost reasoning calls.
- Uses the existing multilingual, classic-text, concept-ledger, evidence-axis,
  claim A-E, contradiction, hypothesis, falsification and scientific-discovery
  layers. It does not replace or duplicate them.
- Records per-round marginal counts without storing source text or URLs in the
  assurance block.

## The 90% target

The `research_process_coverage_percent` is a weighted audit checklist. It covers:

1. all configured search rounds;
2. mandatory evidence-axis search;
3. independent source diversity;
4. legally accessible full-text reading;
5. counter-evidence search;
6. planned reasoning/red-team passes;
7. same-source A-E verification of critical claims, when present; and
8. falsifiable hypotheses with no invented success probability, when present.

Mandatory gaps block `target_met` even if the weighted number reaches 90. A large
source count cannot hide shallow reading, a skipped counter-search, incomplete
reasoning or failed critical-claim verification.

This percentage is **not** an answer-truth probability, trading profitability,
global literature completeness or real-world hypothesis success probability.
Those claims remain prohibited. A hypothesis needs independent prospective
tests/replication before any empirical success rate can be calculated.

## Exact-revision live proof

The normal live release gate remains backward-compatible and defaults to
`MAXIMUM`. An operator with an explicitly confirmed zero-cost model layer can
prove this MARATHON contract on a clean checkout with:

```powershell
.\RUN_LIVE_ZERO_COST_GATE.ps1 -Execute `
  -DepthMode MARATHON `
  -DataRoot "D:\InfinityResearchAI" `
  -Receipt "D:\InfinityResearchAI\audit\live_marathon_gate_latest.json"
```

The sanitized receipt stores only the requested/reported mode, structural
counts, process score/target/gaps, safe status identifiers and an answer hash.
It never stores the question, answer, source text/URLs, credentials or private
capability tokens.

## Saturation honesty

The engine can report a bounded saturation signal when the last two configured
rounds find no new unique URLs. It always keeps
`global_exhaustiveness_claimed=false`: a bounded search can never prove that
every book, paper, archive, language or private/paywalled source was exhausted.
