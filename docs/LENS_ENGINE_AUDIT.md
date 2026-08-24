# Lens Engine independent audit

The Lens Engine is a bounded **search-direction generator**. It may decide what
to search next; it is never evidence, a citation, proof that a thinker made a
claim, or permission to raise answer confidence.

## Corpus feedback admission

After a discovery round, every candidate source is audited before its author,
venue or repeated wording can influence the next search round.

Always excluded:

- retracted records;
- records carrying an explicit rejection reason;
- records whose proposition check is explicitly false; and
- records without any source identity.

When relevance scoring ran, records below the provisional corpus-lens floor
(`0.35`) are also excluded. If relevance did not run, corpus feedback is
fail-closed and no source can supply a lens. The receipt distinguishes `CHECKED`
from `NOT_CHECKED`; an absent relevance run is not reported as a pass or as zero
bad sources. The floor is an exploration control, not a truth threshold.

## Independence and echo-chamber controls

- Repeated frameworks need at least two independent research families.
- A repeated author becomes a thinker-search clue only when the author appears
  across at least two independent families. Multiple URLs/papers from the same
  lead group and method count once.
- Venue ranking counts independent families rather than publication volume.
- DOI identity uses the same canonical DOI normalisation as source deduplication.
- Title and snippet are analysed separately, preventing a fake phrase formed by
  the last word of a title plus the first word of a snippet.

Every admitted corpus-derived candidate carries audit lineage: candidate kind,
supporting source IDs, conservative family keys, independent-family count,
required minimum and whether that floor was met.

## Drift and injection controls

Off-topic/rejected/retracted records cannot steer corpus feedback. Instruction-
like author, venue or phrase metadata is rejected as a search lens. Source text
is still preserved by the evidence prompt guard for legitimate analysis; it is
simply not allowed to manufacture a command-shaped next-round query.

Corpus lenses never enter relevance scoring. The original scoring anchor is
frozen across rounds, preventing a feedback loop in which the engine retrieves
a phrase and then rewards later sources merely for repeating that phrase. The
ordinary base query remains first and query count remains bounded.

## Machine-readable receipt

`lenses_from_sources()` includes an `audit` object with:

- policy version and query-only/evidence flags;
- relevance status, applied floor and its provisional meaning;
- sources seen, eligible and excluded with reason codes;
- `scoring_anchor_frozen`; and
- per-candidate independent lineage.

`merge_corpus_lenses()` preserves this as `corpus_lens_audit`, forces
`verified=False`, retains the original “not citations” evidence status, and
records eligible source/family counts. `lens_summary()` exposes the compact
receipt for downstream UI/audit use.

## Honest limits

This audit reduces research drift and echo amplification; it does not prove that
a lens is useful or that its sources are correct. Author/venue metadata can be
missing or wrong, relevance thresholds remain provisional, and two apparently
independent families may still share undisclosed data or incentives. Final
claims must independently pass the claim-level evidence gates.
