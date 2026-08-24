# Exam Intelligence & Probabilistic Forecasting

This capability converts a **dated, source-traceable** set of past papers and
an official syllabus into study priorities.  It is deliberately not an exact
question predictor and never claims to read an examiner's private thoughts.

## What the production path does

`POST /api/v1/exam-intelligence/analyze` is a project-private, deterministic,
zero-model and zero-network analysis path.  It requires the same
`X-Project-Token` capability as other private project endpoints.

The engine performs these stages:

1. Validate stable paper/question/topic IDs and official syllabus mappings.
2. Reject a paper claimed to be available before its exam date as a possible
   leaked/pre-release record.
3. Exclude papers held or published after the requested `as_of` cutoff.
4. Rank topics and chapters using separate frequency, recency, marks, omission
   and official-syllabus-weight components.
5. Build question-format/cognitive-level practice blueprints without inventing
   exact future questions.
6. Run expanding-window temporal backtests: every held-out paper is predicted
   only from papers available before it.
7. Compare the multi-signal ranker against a frozen raw-frequency baseline.
8. Produce empirical forecast frequencies with Wilson uncertainty intervals
   only after at least 6 temporal splits and 60 topic/outcome pairs.  Otherwise
   every probability field stays `null`.
9. Keep observable historical patterns, existing evidence and app-original
   exam hypotheses in different output fields.
10. Atomically retain a bounded per-project history under the configured
    Infinity data root so the latest analysis can be resumed without rerunning.

## Required input provenance

Each paper needs:

- `paper_id`, `held_on` and preferably `available_from`;
- a source ID and public HTTP(S) source URL;
- question IDs, exact question text, marks and question format;
- one or more mappings to IDs in the supplied official syllabus.

If `available_from` is absent, `held_on` is used as a visible assumption.  A
caller-supplied source URL is preserved only when it passes the public-URL
safety policy.  The analysis labels it as a supplied reference; this
deterministic route does not falsely claim it independently fetched/verified
that URL.

`syllabus_published_at` matters for honest historical testing.  If the supplied
syllabus version was published after a held-out period, the engine reports a
syllabus-hindsight risk and blocks calibration claims.

## Main output separation

| Output | Meaning |
|---|---|
| `study_priorities` | Topic ranking; score is explicitly not probability |
| `chapter_priorities` | Aggregated chapter study ranking |
| `question_pattern_blueprint` | Historical format mix for practice, not exact questions |
| `examiner_pattern_analysis` | Observable paper-selection distributions only |
| `walk_forward_backtest` | Temporal held-out metrics and calibration evidence |
| `existing_evidence` | IDs of supplied papers and syllabus topics |
| `app_original_exam_hypotheses` | Separate untested/falsifiable app proposals |
| `source_ledger` | Exact paper dates, access assumptions and references |
| `honesty_boundary` | Allowed and forbidden public claims |

## Calibration boundary

A `priority_score` answers: *what should receive more study attention under
this transparent heuristic?*  It does not answer: *what is the probability the
examiner will choose this topic?*

Only `CALIBRATED_ON_WALK_FORWARD_HISTORY` may attach an empirical observed
frequency.  Even then the field is labelled
`BACKTEST-OBSERVED FREQUENCY — NOT A GUARANTEE`, includes a Wilson interval and
can drift after a syllabus/policy/paper-setter change.

## App-original hypothesis boundary

Every generated exam hypothesis contains:

- a stable ID and `APP-ORIGINAL EXAM HYPOTHESIS` label;
- supporting observations and strongest counter-evidence;
- assumptions, alternatives and boundary conditions;
- a prospective test, primary endpoint and analysis metric;
- success, failure and falsification thresholds fixed in advance;
- replication, safety/ethics and human-review requirements; and
- no global novelty or success-percentage claim.

If history is too small, hypotheses are not fabricated to reach a count.

## Privacy, storage and legal limits

- Project capability is checked before analysis or ledger access.
- API responses are already covered by the application's `no-store` headers.
- Raw request body is capped at 4 MiB before Pydantic parsing.
- Ledger filenames use a SHA-256 project key, not the raw project ID.
- Writes use atomic replacement plus an OS process lock; corrupt history is not
  silently overwritten.
- Use public, user-owned or otherwise legally available papers.  The system
  must not use leaked papers, login bypasses, private examiner data, DRM/paywall
  bypasses or unauthorized answer keys.

## Current scope

This release is the **forecasting/validation engine and private API**.  It does
not yet claim that arbitrary exam PDFs were automatically discovered, parsed
and correctly topic-tagged.  Discovery/OCR/translation can feed this contract
only after each paper's date, source, reading depth and topic mapping are
validated.  That separation prevents a search snippet or guessed tag from
becoming a confident forecast.

