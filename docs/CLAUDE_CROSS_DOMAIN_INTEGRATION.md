# Claude cross-domain integration audit

This note records the conflict-safe integration decision for Claude main commit `d432d3713b71cebe7f3bd5690ad8eee87abe83ea`.

The integration branch had already evolved beyond that commit, so the main versions were **not** copied over wholesale. That would have overwritten newer research-engine hardening. Instead, the delta was audited semantically and each required behavior was confirmed present on `chatgpt-upload-safety`:

- `research_engine/domain.py`: `Branch.must` reserved search angles and cross-domain profiles are present, plus later multilingual/proximity hardening.
- `research_engine/contradiction.py`: domain-neutral null-result cues and `_all_negated()` are present, plus later claim-level contradiction safeguards.
- `research_engine/relevance.py`: lone-keyword rejection using wide question terms is present, plus later proposition-level relevance checks.
- `research_engine/hypothesis.py`: explicit hypothesis caps respect evidence-gate allowance, including an allowance of 1, plus later provenance/novelty/confidence controls.
- `research_engine/physics_checks.py`: `_restated_from()` validates comparisons against the original quantity, preventing bad conversions such as `730 days (20 years)` from passing.
- `research_engine/claim_labels.py`: `merge_reports()` is present and preserves stricter A-E accounting from this branch.
- `research_engine/orchestrator.py`: strict/depth label reports are merged and explicit hypothesis requests are capped by evidence sufficiency.
- `tests/benchmark_cross_domain.py`: 8-domain benchmark exists and has been extended on this branch.
- `tests/test_answer_structure.py`, `tests/test_consensus_gate.py`, `tests/test_pdf_chunking.py`, `tests/test_relevance_domain.py`: pytest-visible wrappers are present; module-level `SystemExit` no longer breaks pytest collection.

Therefore the main commit can be recorded as merged with a tree-preserving merge commit: ancestry is synchronized without discarding the newer branch implementation.

This audit is **not** a replacement for executing the full release gate. Runtime/CI green proof remains a separate requirement.
