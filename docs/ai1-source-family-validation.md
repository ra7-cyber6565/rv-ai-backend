# AI-1 Source-Family Validation Receipts

The source-family completion work is considered merged only when all of the following are true on one exact feature-head SHA before merge:

1. AI-1 Research Director Gate: success.
2. Foundation tests: success, including strict zero-cost foundation.
3. Anti-confirmation attestor: success.
4. Model reality attestors: success.
5. AI-2 Validation Director Gate: success.
6. Pull request is mergeable against current `main` and is not behind it.
7. Merge uses `expected_head_sha` equal to the validated feature head.

## PR #74 — thesis/archive/anatomy/source-family matrix

Validated head: `e9d174007085cab79f5c086ce60f8995c9786ce6`

- AI-1 Research Director Gate: success.
- Foundation tests: success.
- Anti-confirmation attestor: success.
- Model reality attestors: success.
- AI-2 Validation Director Gate: success.
- Branch comparison before merge: ahead of `main`, behind by 0.
- Pull request mergeability before merge: true.
- Merge commit on `main`: `96869c3254c17f6fa0fe0f34d95a466370b17e35`.

## PR #75 — documentation/media/multilingual final runtime coverage

Validated head: `f763fcca1145e77511d98932bb7df6bc9c58cecb`

- AI-1 Research Director Gate: success.
- Foundation tests: success, including advanced regression and strict zero-cost foundation.
- Anti-confirmation attestor: success.
- Model reality attestors: success.
- AI-2 Validation Director Gate: success.
- Branch comparison before merge: ahead of `main`, behind by 0.
- Pull request mergeability before merge: true.
- Merge commit on `main`: `98bec29ec71840aa8dd7ce5e6688a2adaece2a4f`.

## Truth boundaries that remain mandatory

- Search/discovery/metadata is not reading.
- Dissertation metadata/abstract is not thesis-body review.
- Archive catalog description is not archive-body review.
- One documentation page is not a whole manual or whole site.
- Bounded dataset/code/document sections are not the complete dataset/repository/document.
- Transcript/caption text is not watched/listened audio-visual analysis.
- OCR/transcription/translation capture quality does not prove the underlying claim true.
- Original multilingual text read is not automatically a verified translation.
- Patent claims are legal claims, not scientific validation.
- Anatomy completeness is not study validity, replication or truth.
- Implementation availability is distinct from whether a capability was exercised in a particular run.
- Paywalled/private/authenticated/unavailable sources remain unavailable rather than being overclaimed.
