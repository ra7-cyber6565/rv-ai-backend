# Final Quality Gate integration contract

`research_engine.final_quality_gate` is an offline, fail-closed release gate.
It does not retrieve sources, call an AI provider, rewrite prose, or silently
repair evidence.  The orchestrator/synthesizer must record structured facts;
the gate judges those facts immediately before the final result is persisted or
returned.

## Public API

```python
from research_engine.final_quality_gate import evaluate_final_quality

quality_gate = evaluate_final_quality(result_dict, quality_contract)
result_dict["quality_gate"] = quality_gate
```

The returned mapping always contains:

- `score`: integer `0..100`;
- `status`: `PASS_100`, `BLOCKED_REVIEW`, `PARTIAL`, or `FAIL`;
- `release_ready`: true only at exactly 100 with every check passing;
- `verified_allowed`: whether a VERIFIED badge is allowed;
- `answer_complete`: requested answer completeness, not network-job completion;
- `hard_cap`: the strongest hard cap triggered;
- per-category scores, individual checks, and structured issues.

## Required integration order

1. Parse explicit user deliverables into `quality_contract`.
2. Retrieve and rank evidence.
3. Perform support and counter-searches.
4. Build claim-level evidence spans and access-depth checks.
5. Generate the sourced answer.
6. Generate original hypotheses in the separate schema, when requested.
7. Validate calculations and hypotheses.
8. Assemble the final user-facing answer once.
9. Run `evaluate_final_quality`.
10. Persist the quality report with the result.
11. If `verified_allowed` is false, remove/downgrade VERIFIED before returning.
12. If `answer_complete` is false, never return answer status `COMPLETE`.

The gate must run on normal completion, provider fallback, recovered jobs and
cached-result paths.  A path that bypasses the gate is a release blocker.

## `quality_contract`

```python
quality_contract = {
    "required_sections": [
        "direct_answer",
        "established_knowledge",
        "supporting_evidence",
        "counter_evidence",
        "calculations",
        "unknowns",
        "conclusion",
        "original_hypotheses",
        "sources",
    ],
    "hypotheses_requested": 3,
    "original_hypotheses_required": True,
    "calculations_required": True,
    "counter_search_required": True,
    "evidence_graph_required": True,
    "minimum_directly_relevant_sources": 2,
    # This is provisional and must be calibrated on the benchmark corpus.
    "minimum_average_relevance": 0.65,
}
```

Only explicitly requested or domain-required deliverables belong in the
contract.  Do not mark calculations/hypotheses required for every ordinary
chat question.

## `quality_context`

The final result should expose:

```python
quality_context = {
    "counter_search_performed": True,
    "directly_relevant_sources": 6,
    "sources_retrieved": 6,
    "sources_cited": 5,
    "sources_supporting_critical_claims": 4,
    "unsupported_critical_claims": 0,
    "critical_no_source_claims": 0,
    "access_depth_mismatches": 0,
    "critical_claim_spans_complete": True,
    "critical_claim_evidence_spans": [
        {
            "claim_id": "C1",
            "source_id": "S2",
            "passage": "Exact supporting text",
            "locator": "page 4",
        }
    ],
    "evidence_graph_complete": True,
    "hypothesis_fact_mix_count": 0,
    "numeric_confidence_calibrated": False,
    "recovery_used": False,
    "progress_snapshot_preserved": True,
    "calculations": [],
}
```

The four source counters mean different things and must not be derived from
one generic `len(sources)` value.

## Calculation record

Every requested calculation must provide:

```python
{
    "formula": "M = v^2 r / G",
    "inputs": {"v": 220, "r": 8.2, "G": 6.6743e-11},
    "units": {"v": "km/s", "r": "kpc", "result": "solar masses"},
    "assumptions": ["circular orbit", "spherical approximation"],
    "result": "9.2e10 solar masses",
    "uncertainty": "Illustrative; disk geometry excluded",
    "unit_check_passed": True,
    "recalculation_passed": True,
    "sanity_check_passed": True,
    "invented_input": False,
}
```

No hidden “numeric check passed” statement is acceptable without this record.

## Original-hypothesis record

App-generated hypotheses must be outside established/source-reported answer
sections and use this minimum schema:

```python
{
    "hypothesis_id": "RV-HYP-2026-001",
    "statement": "Bounded, measurable statement",
    "provenance": {
        "facts_used": ["C1", "C4"],
        "gap": "What the evidence does not explain",
    },
    "mechanism": "Causal/physical mechanism",
    "source_claim_disclaimer": (
        "No cited source reports this exact conclusion; it is app-generated synthesis."
    ),
    "closest_prior_work": [
        {"source_id": "S4", "similarity": 0.61, "difference": "Exact novelty delta"}
    ],
    "novelty_search": {
        "queries": ["exact", "synonym", "mechanism", "negative prior-art"],
        "databases": ["OpenAlex", "arXiv", "Crossref"],
        "close_match_found": False,
    },
    "novelty_status": "POSSIBLY NOVEL — NO CLOSE MATCH FOUND",
    "assumptions": ["Explicit assumption"],
    "prediction": {
        "variables": ["x", "y"],
        "expected_outcome": "Bounded expected result",
        "measurement_method": "Reproducible method",
        "falsification_condition": "Bounded rejection condition",
    },
    "experiment": {
        "dataset_or_sample": "Pre-registered sample",
        "control_or_baseline": "Existing-model baseline",
        "measured_variables": ["x", "y"],
        "parameter_range": "Fixed bounded range",
        "statistical_metric": "Pre-selected metric",
        "success_threshold": "Pre-selected threshold",
        "failure_threshold": "Pre-selected threshold",
        "falsification_condition": "Exact rejection condition",
    },
    "confidence": {
        "level": "LOW",
        "reason_codes": ["untested mechanism"],
    },
    "validation_status": "Concept only",
}
```

Allowed novelty labels are intentionally bounded:

- `KNOWN IDEA`
- `KNOWN VARIANT`
- `MINOR MODIFICATION`
- `POSSIBLY NOVEL — NO CLOSE MATCH FOUND`
- `NOVELTY UNVERIFIED`
- `REJECTED AS DUPLICATE`

Never emit “100% new”, “world first”, or “research does not exist” from an
ordinary database search.  If a defensible candidate does not survive the
novelty/red-team checks, returning no hypothesis is scientifically preferable
to fabricating one.  When the user explicitly requested a fixed count, record
the shortfall and return a partial answer rather than filling the count with
duplicates.

## Structured contradiction record

A contradiction needs all of:

```python
{
    "normalized_proposition": "Intervention X changes outcome Y",
    "source_a_claim": "X increased Y in population P",
    "source_b_claim": "X did not increase Y in population P",
    "opposing_direction": True,
    "evidence_spans": ["S1 page 4", "S2 page 7"],
    "method_difference": "Different measurement precision",
}
```

Different publication years, topics or generic confidence descriptions do not
constitute a contradiction.

## Failure behavior

- Never rewrite structured failures into a pass.
- Never replace `quality_gate` with a model opinion.
- Never show VERIFIED when `verified_allowed` is false.
- Never show COMPLETE when `answer_complete` is false.
- Preserve issues in the API result so the UI can explain the exact failure.
- Keep provider/debug details outside `answer`.
- On recovery, run the gate after deduplication and include the final progress
  snapshot.

## Tests

`tests/test_final_quality_gate.py` is the authoritative offline contract.  It
covers the 100-point pass, hard caps, false VERIFIED, irrelevant source packs,
claim/source mismatch, access-depth mismatch, fake contradiction, missing
calculation, unbounded novelty, hypothesis/fact mixing, weak falsification,
raw-log leakage and duplicate recovery output.
