# Evidence mutation matrix

This gate asks a stricter question than “does the happy-path example pass?”:
does one small but meaningful mutation make an unsafe evidence claim fail?
Every case is deterministic, offline and zero-cost.

| Mutation | Required invariant |
|---|---|
| Same DOI as raw text, `doi:` prefix, DOI URL, mixed case or tracking query | One work/independence voice; canonical DOI identity. |
| Same DOI with metadata-only copy first and full-text copy later | Keep the deepest access/text while preserving monotonic safety signals such as retraction. |
| Translated/different title but same DOI | Collapse by DOI, not language/title surface form. |
| Identical title but two explicit different DOIs | Retain two studies; title similarity cannot override conflicting strong identities. |
| Retraction appears after pre-draft manifest capture | Current same-source A–E quality gate fails; old eligibility cannot retroactively certify the claim. |
| Source access is downgraded after capture | Current reading-depth gate fails; prior/full-text-looking passage cannot promote it. |
| Citation is moved to the next bullet | Previous strong claim remains uncited and unverified. |
| Same passage/source but different locator | Preselection binding fails. |
| Generic “exact page unavailable” placeholder | Cannot qualify as exact support or exact contradiction provenance. |
| Search snippet with a real-looking page string | Still cannot qualify as an exact contradiction span because its span kind is `snippet`. |
| Opposing keyword in a distant paragraph | Cannot bleed into the canonical claim span. |
| Opposing passage is mutated to neutral wording | Contradiction disappears. |
| Hostile multiline title/PDF metadata | Remains quoted untrusted source data and cannot escape into prompt instructions. |
| `-23 °C` becomes `23 °C` beside `250 K` | Unit-conversion check turns red. |
| Evidence text/hash, source, locator, question or selection policy changes | Manifest identity/binding changes or final audit fails. |

## DOI merge policy

DOI identity is case-insensitive and normalizes `https://doi.org/`,
`http://dx.doi.org/`, `doi:`, URL encoding, fragments and query parameters. An
invalid non-DOI string is never promoted to DOI identity.

For an exact DOI/URL duplicate, retraction remains monotonic (`True` wins),
missing methodology/disclosure metadata may be filled, and the deeper/longer
text access supplies read fields. The output records that duplicate copies were
merged. Near-title matching alone is not allowed to transfer text/read depth.

## Shared locator policy

Pre-draft manifests, post-draft claim verification and the final release gate
now use one placeholder-rejection policy. A critical contradiction additionally
requires:

- `span_kind == "passage"`;
- non-placeholder page/section/paragraph locator;
- attributable source id and substantive opposite passage; and
- explicit opposite support/oppose directions.

This prevents the old shape where a long placeholder string satisfied a mere
“locator is non-empty” check.

## Gate position

`tests/test_evidence_mutation_matrix.py` is part of the focused Foundation gate.
The existing locator-binding, capture-provenance, claim-level contradiction,
prompt-injection, physics and full-domain benchmarks continue to run as
independent regression layers.

