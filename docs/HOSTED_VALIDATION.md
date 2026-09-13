# Hosted validation and retained research data

This continues the existing Infinity Research AI application in PR #79. It
does not create another app. The user's Windows checkout, existing files and
Railway production configuration are not changed by hosted testing.

## What is executable

Normal Foundation CI installs dependencies on a GitHub runner, runs the offline
suite, executes real Python/Node containers and protected improvement trials,
and starts the actual API for a localhost smoke check. These jobs do not need
laptop installations. The optional final live step invokes the existing public
agent manager in COMPANY and COMPANY_PLUS modes, sequentially, then the fixed
US100/XAUUSD MAXIMUM trading acceptance lane. Failed company prerequisites skip
that extra allocation. The lane validates runtime/delivery/fail-closed behavior;
it does not certify historical backtest correctness or independent quality.

The optional step requires all of the following:

- A manual `workflow_dispatch` with `live_company=true`.
- Public repository `ra7-cyber6565/rv-ai-backend`, standard GitHub-hosted Linux
  runner, and a clean checkout matching the full `reviewed_commit` input.
- Passing foundation, real container tests with zero skips, and the actual
  localhost API smoke from this exact commit, workflow run and run attempt.
- An explicit model identifier and dedicated private provider credentials that
  satisfy the application's confirmed-free eligibility guard.

Credentials are scoped to the stdlib-only no-network settings check and the
final live step; dependency installation and regression tests do not receive
them. A push, PR, rerun of a
normal offline workflow or missing prerequisite cannot start this live lane.
The runner executes fixed gate questions; it has no arbitrary-command or
user-question workflow input. Checkout does not persist GitHub credentials.

## Private operator configuration

In this repository's **Settings → Secrets and variables → Actions**, configure:

| Kind | Name | Value |
|---|---|---|
| Secret | `INFINITY_LIVE_GEMINI_KEY` | The approved provider API key |
| Secret | `INFINITY_LIVE_ZERO_COST_CONFIRMED` | `true` only after verifying that this account/model use has no charge |
| Variable | `INFINITY_LIVE_GEMINI_MODEL` | The exact eligible model identifier |

Do not put these values in a commit, issue, PR body or chat. The confirmation
flag is an operator assertion, not a provider billing audit. If free eligibility
cannot be established, leave it unset and the live step remains blocked.

Open **Actions → Foundation tests → Run workflow** and select
the current reviewed PR branch (`codex/answer-scope-20260908` for PR #82).
Use the full reviewed commit SHA, not the
short display hash, and enable `live_company`. Review the branch code before
providing credentials. No merge or Railway deployment is part of this action.

GitHub requires a dispatchable workflow registered on the default branch. This
repository already has Foundation tests there; the new inputs are on the PR
branch. If the browser displays only the default-branch form and does not show
these inputs, do not treat a run without them as live validation. An authorized
operator can use GitHub's documented dispatch API/CLI with the branch `ref`
and both inputs from an already configured environment. This implementation
was manually dispatched on PR #82 head c320d59a61f3c5946b18ae08d3f61e35960f3cc3
in run 34452317616. Attempt 2 passed setup/prerequisites but failed COMPANY
execution. That failure does not validate a newer candidate or provider access.

## Quota failure and retry coordination

Run 34699631516 returned RESEARCH INCOMPLETE with daily_quota/rate_limit and
model_not_found classifications: 22 recorded worker/chief model attempts,
zero successful calls and zero hypotheses. This is not a reason to repeatedly
redispatch a full company campaign. Check the same Google project's current
[AI Studio rate limits](https://aistudio.google.com/rate-limit) first; the
[official guide](https://ai.google.dev/gemini-api/docs/rate-limits) explains that
limits apply per Google project, not per API key. Actual remaining capacity is
private/UNKNOWN; a new key does not itself establish additional capacity.

Workers and chief now share model/credential cooldown observations through the
existing SQLite run. Holds are confined to that app tenant/run; no other model,
credential or provider is inferred unavailable from a model-specific failure.
Daily/model-not-found/auth holds expire with the bounded run, and rate-limit
holds expire after the provider delay or existing retry backoff. In-flight
attempts admitted before an observation may finish. Skips record attempt=0 and
origin=shared_run_cooldown rather than inventing failed HTTP calls. Runtime
events contain fixed provider/kind fields, not credentials or model labels.
This saves repeated calls; it does not raise quota, complete missing research,
change free-provider eligibility or prove real-world answer quality.

## Receipts and interpretation

Only the sanitized `hosted_live_gate.json` is uploaded from the live directory.
It contains commit/run identity, mode/check outcomes and test status, not API
keys, questions, retrieved source text or raw provider responses. Artifact
retention is one day. Raw live files remain in the disposable hosted workspace.
GitHub Actions is a test host, not a permanent research archive or 24-hour app
host. Use only the fixed public gate campaign here; do not place a user's sole
copy of research data in this ephemeral workspace.

Failure receipts also carry fixed failure codes and bounded error categories,
with module names and line numbers from Git-tracked public Python code only.
They omit raw messages, private filenames, locals, source/provider payloads and
arbitrary exception/function names. Missing Git inventory omits locations.
The hosted boundary revalidates child diagnostics. These fields locate a
failure for review; they do not independently establish its root cause.

Returned-but-incomplete research now retains an allowlisted summary as well:
requested_depth_mode and reported_depth_mode, result/discovery status, source
and hypothesis counts, provider error categories, missing passes, bounded
worker status/error/call counters and chief execution passes/counters. Missing
or invalid counters remain null. The child and hosted boundary both validate
company diagnostics; the host excludes model labels, arbitrary identifiers,
worker IDs, answer hashes and raw text. These fields never make a failed gate
pass. Executed mode comes from ResearchResult.mode, not coverage.mode; missing
canonical mode or conflicting legacy coverage.mode fails the mode check.

`LIVE_GATES_PASSED` requires both company modes and the fixed trading Max lane
to pass their respective strict gates. Inspect trading_max as well as modes.
Even then, `release_ready=false`, `quality_benchmark=NOT_TESTED`, and
`production_deployed=false`. Offline fixture tests of this runner are not
evidence that live models ran. The exact PR head and Actions receipts are the
acceptance source; older commits' green checks do not validate later edits.

## Data preservation is the default

`INFINITY_PRESERVE_STORED_DATA=true` is the default, including when the variable
is missing or misspelled. Archive uploads can still be verified, but automatic
cleanup and `delete_local` requests keep the stored local copy. Durable job
history, expired runtime checkpoints and improvement proposals are not evicted
to admit newer work. Expired checkpoints remain expired; retaining evidence
does not extend execution permission.

Full stores pause new work. Existing reading sessions remain readable;
unfinished PDF copies from an earlier crash block new session creation until
recovery. This change does not invent missing session metadata. Existing
user-authorized memory correction/delete/clear commands remain available, and
temporary files created by a failed operation can still be disposed of.

The operator may opt into legacy retention only with explicit owner permission
by setting the flag to `false`. Existing legacy-policy tests use that explicit
setting; separate default-on tests verify actual file retention, full-store
rejection, transaction behavior and reading results after process restart.

`INFINITY_MAX_LOCAL_GB` and free-space checks are application admission guards,
not an operating-system quota. The live lane uses a separate data root and a
2 GB application limit. Dependencies, container layers, other processes and
simultaneous writes are outside a hard total-disk guarantee. Unlimited work,
finite capacity and never deleting data cannot all be guaranteed together;
verified additional storage is needed when retained data reaches capacity.

## Still unverified or unavailable

- Exact-head confirmed-free live model execution and independent held-out
  quality comparison against a single-agent baseline.
- A persistent production data volume/archive and its backup/restore proof.
- A production-compatible isolated executor. The CI Docker runner does not
  establish Docker availability inside the existing Railway container.
- The user's local commit `7e36911` and modified/untracked modules. They have
  not been uploaded here and cannot be merged safely from filenames alone.
- Target deployment, Windows runtime and physical/clinical experiment results.

No feature is marked removed to hide these gaps. All 22 requirements remain in
`INFINITY_REQUIREMENT_LEDGER.md`.

Official workflow references:

- https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow
- https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets
