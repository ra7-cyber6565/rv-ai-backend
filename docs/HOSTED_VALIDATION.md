# Hosted validation and retained research data

This continues the existing Infinity Research AI application in PR #79. It
does not create another app. The user's Windows checkout, existing files and
Railway production configuration are not changed by hosted testing.

## What is executable

Normal Foundation CI installs dependencies on a GitHub runner, runs the offline
suite, executes real Python/Node containers and protected improvement trials,
and starts the actual API for a localhost smoke check. These jobs do not need
laptop installations. The optional final live step invokes the existing public
agent manager in COMPANY and COMPANY_PLUS modes, sequentially. It stops when a
mode fails and retains an honest failure receipt.

The optional step requires all of the following:

- A manual `workflow_dispatch` with `live_company=true`.
- Public repository `ra7-cyber6565/rv-ai-backend`, standard GitHub-hosted Linux
  runner, and a clean checkout matching the full `reviewed_commit` input.
- Passing foundation, real container tests with zero skips, and the actual
  localhost API smoke from this exact commit, workflow run and run attempt.
- An explicit model identifier and dedicated private provider credentials that
  satisfy the application's confirmed-free eligibility guard.

Credentials are supplied only to the final live step. A push, PR, rerun of a
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
`codex/research-company-20260905`. Use the full reviewed commit SHA, not the
short display hash, and enable `live_company`. Review the branch code before
providing credentials. No merge or Railway deployment is part of this action.

GitHub requires a dispatchable workflow registered on the default branch. This
repository already has Foundation tests there; the new inputs are on the PR
branch. If the browser displays only the default-branch form and does not show
these inputs, do not treat a run without them as live validation. An authorized
operator can use GitHub's documented dispatch API/CLI with the branch `ref`
and both inputs from an already configured environment. This implementation
has not verified that browser form or performed a manual live dispatch.

## Receipts and interpretation

Only the sanitized `hosted_live_gate.json` is uploaded from the live directory.
It contains commit/run identity, mode/check outcomes and test status, not API
keys, questions, retrieved source text or raw provider responses. Artifact
retention is one day. Raw live files remain in the disposable hosted workspace.
GitHub Actions is a test host, not a permanent research archive or 24-hour app
host. Use only the fixed public gate campaign here; do not place a user's sole
copy of research data in this ephemeral workspace.

`LIVE_GATES_PASSED` requires both modes to pass their existing strict gates.
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
