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
workflows. It owns technical-script intent and trading-hypothesis structure;
this branch does not overwrite those files. Its remaining advertised numeric
provenance/handoff acceptance work is not counted as complete from that CI.

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
