# Answer-condition acceptance repair

Base: main `831dbc7209253e58bbfa0ec79b9efe8e130bf523`.
Branch: `codex/answer-scope-20260908`.

## Observed failure and implemented repair

The user supplied a rendered answer, not its original JSON/source pack. It
answered an atmospheric-pressure superconductivity question with a 1 GPa source
report and a ceramic-signatures report whose quoted pressure was unspecified.
The conclusion repeated a report, the mechanism section repeated a question,
and the public PARTIAL reason described the earlier COMPLETE label.

| Defect | Repair | Remaining limit |
|---|---|---|
| A relevant source is treated as if it addresses the requested pressure | Pre-draft scope metadata and condition labels; unresolved fallback states INCONCLUSIVE before reports | Mentions are not measurement provenance or confirmation |
| A reported claim can lose its adjacent negative follow-up during sentence selection | Preserve adjacent however/but/yet/nevertheless qualification | Nonadjacent negation and arbitrary discourse still need semantic evaluation |
| A question appears as a mechanism | Exclude question-ending sentences from factual selection | Declarative causal prose still needs causal evidence |
| Public PARTIAL text says job is COMPLETE | Describe corrected state and missing sections; preserve original issue in structured audit | Missing deliverables remain missing |
| All headings can mask unresolved conditions in the critical fallback | Carry the fallback scope failure into release completeness; invalidate old contract 1.0 receipt | A scientifically inconclusive but completed review is not automatically incomplete |

No source is promoted to independently replicated evidence by these changes.
The existing relevance, access-depth, retraction and same-source A–E gates remain.
The prompt also distinguishes source signatures, app hypotheses, proposed tests,
executed tests and the invalid leap from rejecting a mechanism to requiring new
fundamental theory. Prompt instructions are not proof of model compliance.

## Exact test scope

TEST PERFORMED: `python tests/test_evidence_pressure_scope.py` — eight stdlib
test methods passed locally. This includes equivalent units, 1 GPa/10 kbar,
mixed/unspecified conditions, near-ambient wording, malformed values and unknown
scientific confirmation. Syntax and whitespace checks also passed.

TEST PROPOSED / CI REQUIRED: `tests/test_p0b_evidence_before_generation.py` and
`tests/test_quality_release.py` plus the full five required repository workflows.
The PR's exact head and run receipts supersede this at-authoring pending state.
The source-answer fixture is adapted from the user's report; it is not a live
replay, independent holdout, fresh literature search or physical experiment.

The standard-atmosphere reference is exactly 101325 Pa; conversion factors are
from NIST SP 811 Appendix B. No experimental tolerance is guessed. Values such
as 0.1 MPa are recorded as numerically different from one standard atmosphere,
not declared physically incompatible with ambient laboratory work. The parser
does not estimate local atmospheric pressure. Unit spelling is case-sensitive;
unparsed notation remains unknown. These limits require review, not fake proof.

Primary context checked during diagnosis:

- NIST units: https://www.nist.gov/pml/special-publication-811/nist-guide-si-appendix-b-conversion-factors
- Original Lu-H-N claim with retraction notice: https://www.nature.com/articles/s41586-023-05742-0
- Independent resistance-upsurge analysis abstract: https://arxiv.org/abs/2307.00201

The retracted original paper and a later paper criticizing it must not be
conflated. The ceramic source's identity/status was not independently verified.
No exhaustive current-literature conclusion is claimed by this repair.

## Parallel work and next acceptance

Sol PR #81 was read at `0a75e6a048b1f032206f3b9a8e02e907b6ad3649` with five green
workflows. This branch incorporates those five changed files as a reviewed
snapshot and repairs two independently reproduced boundary failures:

- `Write a Python script to count characters in a string` and `...analyse
  conversation logs` were returned as creative dialogue. Narrow input-data
  phrase handling corrects these while preserving explicit screenplay/dialogue.
- A walk-forward plan with `success if UNKNOWN`, `fail if UNKNOWN` and
  `no baseline has been selected` was returned with `is_complete=True` and a
  populated baseline. Explicit missingness stays empty in the structured plan;
  raw original prose stays available and ordinary no-trade baselines survive.

TEST PERFORMED: 13 module-isolated craft/trading regression functions passed
with actual source modules and their stdlib dependencies. This bypassed package
bootstrap only because local integrated dependencies are unavailable; it is not
an API/live execution receipt. The final combined head must pass normal CI.
Sol's active branch was not overwritten or moved. Refresh it before later
integration; his future edits are not included by this snapshot. His advertised
numeric-provenance/handoff acceptance work is not counted complete from CI.

2026-09-09 current-state review: main remains `831dbc72`; Sol has advanced to
`1666028619b99d4b6dfeb904102aa5327800a7c6`. Foundation run 34241520688 failed with
two cases. Other four workflows passed. This newer wave is not incorporated
into the reviewed `0a75e6a` snapshot; its active branch remains untouched.

1. `test_rich_structured_reports_use_bounded_handoff_without_false_10_of_11_gap`
   expects four completed workers from a raw fixture above the existing 24,000
   character worker/parser capture bound. All four are rejected before handoff.
   Keep a bounded valid-worker fixture separate from a deliberately oversized
   failure case; do not raise limits or claim full capture merely for green CI.
2. `test_overlong_handoff_keeps_every_role_and_blocks_complete_review`: the new
   sorted JSON places role metadata after a long report; clipping can remove
   that role. Put trusted role/status identity before the bounded source text.
3. Review concern from source inspection, not a live test: compact/ULTRA views
   clip falsification/threshold text and reduce some plan fields to names. Full
   reports retained elsewhere do not prove the chief read omitted content.
   A complete handoff must preserve decision-relevant content or stay PARTIAL.
4. Numeric-provenance review concern: a sentence saying "calibrated from 100
   samples" is not itself a measured execution receipt. Existing provenance
   checks must bind that statement to a real structured receipt before relying
   on it. A citation marker alone is still subject to the downstream A–E gate.

Initial PR #82 gate at `8e69f04746b447bf21c9ba355c373a70fc27bfd1`: 4,219 tests
passed, one failed because a legacy API test pinned contract 1.0. The new
condition gate intentionally requires 1.1 to invalidate cached old decisions.
The assertion was updated; no quality threshold or negative case was relaxed.
Four other workflows passed. Final combined-candidate CI remains required.

After reviewed integration, rerun all mandatory gates on the combined head and
verify deployment identity. Then submit the same public Max question, capture
raw JSON, source IDs/URLs/read depth, condition audit, all requested sections,
and six-worker/chief receipts when a confirmed-free provider is available.
Grade the actual answer for pressure/temperature/material scope, original versus
replication versus retraction, coherent hypothesis/null/falsification, stated
units/controls/sample needs, and proposed-versus-performed labels. Missing
sample-size inputs must remain TO BE ESTIMATED; do not invent them to pass.

Scientific and live-model outcomes remain NOT TESTED for the new revision.
Persistent production storage, real executor host, representative independent
benchmark and unavailable Windows changes remain open in `AI_HANDOFF.md`.
