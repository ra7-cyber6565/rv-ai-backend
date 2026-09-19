# PR #81 reviewed acceptance repairs — 2026-09-19

Status: AUTHORIZED FOR PR #81 INTEGRATION / FULL VERIFICATION PENDING.


Latest-main reconciliation: the direct `refs/heads/main` is
`3bf8f4a2ec5ff9c61daea2dadd536f7cbd42ed9a` (PR #84), not the stale base SHA
returned in PR #81 metadata. Its durable/ephemeral storage split, MB quota
controls and persistence runbook are merged into this acceptance branch without
changing their implementation. The combined selected storage/runtime/acceptance
suite passed 118 tests in 2.65s. The older 831dbc7 main statements below are
historical. Full CI and live checks must run again on this integrated head.

Production read-only inspection: the September 15 deployment at 3bf8f4a was
REMOVED on September 19; `/health` currently returns HTTP 404. The service still
points to this repository's `main`, but an active healthy deployment and durable
volume are not established. Do not inherit older SUCCESS claims or deploy paid
resources. Follow `docs/PERSISTENCE_RUNBOOK.md` for the actual-host proof.

## Revision and evidence

- Parent: `1449adfefc5df53edec5368b17efd9e0478d408d`.
- Review branch: `fix/pr81-reviewed-gates-20260919`.
- PR #81 remains OPEN, DRAFT, mergeable and unmerged at the parent.
- Current main read from GitHub: `831dbc7209253e58bbfa0ec79b9efe8e130bf523`.
- On the parent, AI-1, AI-2, Model Reality and Anti-confirmation passed;
  Foundation `34819416934` failed its strict foundation step.
- Parent live run `34819411583` failed. Prior inspected sanitized telemetry
  showed 0/6 ready specialists, 17 HTTP attempts, one provider success, no
  validated reports, three process deadlines, two no-output failures and one
  invalid report. A successful synthetic preflight request is not Company proof.

## What this checkpoint changes

1. The fresh-process import test verifies the complete handoff wrapper chain:
   Round-2 cross-review -> compatibility guard -> canonical research_company.
   Updating only the expected module name would miss a bypass of the guard.
2. The trading evaluator reads public top-level `mode`, where ResearchResult
   places MAXIMUM, instead of expecting it in the coverage dictionary.
3. First-pass completion requires six distinct roles and worker IDs, validated
   reports, complete output capture/accounting and positive provider attempts
   and successes. Failed drafts cannot earn complete-handoff credit.
4. Round 2 requires six separately identified reviews, all five other roles
   reviewed per specialist, actual usage receipts and the recorded review phase.
   Missing, clipped or incomplete peer handoffs fail the acceptance gate.
5. Both cross-review check names survive the existing receipt-only diagnostic
   allowlist. Free-form peer text is never copied to its public summary.

The initial acceptance commit `7b0a10de7831efbca342ee361ea5fd68170c3a6b`
reuses the existing Company, cross-review and handoff paths. That commit changes
no provider selection/retry policy, output ceilings, workflows or deployment.
The runtime follow-up below modifies deadline and retry accounting in place.

## Validation performed

Python 3.12.14, pytest 8.3.4, sympy 1.13.3. The following selected tests completed
with **46 passed in 3.63 seconds**. Git whitespace validation also passed.

```sh
python -m pytest -q \
  tests/test_pr81_trading_live_acceptance.py \
  tests/test_pr81_live_failure_diagnostic.py \
  tests/test_pr81_worker_diagnostics.py \
  tests/test_company_cross_review.py \
  tests/test_company_handoff_runtime_wiring.py
git diff --check
```

These are deterministic synthetic-envelope and injected-provider tests. One case
runs the real Company orchestration/normalization/handoff with fixture provider
responses and checks that the evaluator accepts its receipt shape. It explicitly
does not claim that the overall trading/live gate passed. No generation SDK or
actual provider is needed by this selected suite. CI uses Python 3.11 and must
still verify the integrated revision independently.

## Runtime repair follow-up — 2026-09-19

The same review branch now includes a cooperative generation window in the
existing runtime/router. The parent supplies the absolute cutoff, reserving ten
seconds before its 180-second kill deadline; child startup consumes that window.
Discovery, generation, retry backoff, key rotation and provider fallbacks consult
one monotonic remaining-time budget. Nested scopes cannot enlarge it. Existing
provider eligibility and the 6,000-token output ceiling are preserved.

A 75s + 75s timeout sequence now gives recovery at most the remaining 20 seconds,
instead of starting a new 180-second request. Fast primary failure can still use
a confirmed-free provider or backup key. SDK-internal retries are disabled in
the worker even without a bound durable run. Retry/compaction/recovery counts are
charged only after a request lease; an adapter rejection before dispatch is not
reported as an HTTP attempt. Cooperative expiry and rejected central leases keep
prior numeric receipts. Invalid JSON still cannot become DRAFT_READY.

**108 tests passed in 1.94 seconds**, including the 46 acceptance/wiring cases
above, 17 new clock/provider regressions, and existing retry/router regression
cases. Reproduction uses the same small Python environment:

```sh
python -m pytest -q \
  tests/test_company_generation_window.py \
  tests/test_gemini_retry.py \
  tests/test_reasoning_router.py \
  tests/test_reasoning_router_integration.py \
  tests/test_pr81_trading_live_acceptance.py \
  tests/test_pr81_live_failure_diagnostic.py \
  tests/test_pr81_worker_diagnostics.py \
  tests/test_company_cross_review.py \
  tests/test_company_handoff_runtime_wiring.py
git diff --check
```

These tests use injected clocks, SDKs and HTTP responses; no actual model call
was made. They cover slow timeout/recovery, successful compact recovery, fast
primary-to-free fallback, hosted/local fallback timeout allocation, discovery
using the same budget, backup-key rotation, exhausted central lease, backoff
expiry, no phantom last-slot retry, unsupported unbounded adapters, expired
parent cutoff, invalid JSON, hard process death, fallback-only expiry accounting
and nested-window isolation.

This is cooperative bounding, not proof that an arbitrary SDK, DNS lookup,
paginated discovery or a trickling HTTP body must stop at an exact wall-clock
instant. The parent's hard subprocess timeout remains the final boundary and
still marks killed-process accounting incomplete/UNKNOWN. Real SDK compatibility,
provider latency, structured-output quality and full exact-revision CI are
VERIFICATION PENDING. No merge, deployment or live acceptance is claimed.

## Measured defect and rejected earlier proposal

The worker subprocess has a 180-second outer deadline. The Gemini loop can make
75-second calls and then a 180-second recovery call; a process can therefore be
killed before completing the planned recovery and serializing usage. This is a
measured contributing defect, not proof that all live failures have one cause.
Invalid structured output and other provider failures remain separate issues.

An earlier scratch proposal set one model/key/attempt and a 165-second request,
reduced worker output to 3,000 tokens, and applied a one-attempt profile to chiefs.
Do not apply that proposal blindly:

- Per-call timeout does not by itself bound model discovery, backup-key setup,
  fallback-provider timeouts and output serialization across the whole process.
- Capping every pass to one attempt can suppress a functioning confirmed-free
  fallback after a fast primary error. Max's fallback-capable chief is required.
- A 3,000-token ceiling has not been shown to fit the full JSON/tool code and
  hypothesis contracts. Truncated JSON would recreate invalid-report failures.
- Logical call counts are different from HTTP attempts. A plan of 16 logical
  calls is not evidence of a provider allowance of exactly 16 or 20 requests.
- Retry and compaction counters must count dispatched retries, not merely a
  proposed retry when no attempt slot remains.

The runtime follow-up above implements and locally tests this repair within
the existing router. The next evidence required is actual provider compatibility
and a complete live Max receipt on the integrated revision.

## Owner authorization — 2026-09-19

After the automatic-review rejection and payload/destination were explained,
the owner explicitly authorized test prompts and public source/repository excerpts
to Google Gemini for confirmed-₹0 CI/live verification. Promote the reviewed
acceptance/runtime commits through `8febb75fc5ba7d66d2759ddb0bfdf845f14b84f8`
into the existing PR branch and inspect the resulting exact-head receipts.
The permission boundary below is historical; no repeated approval is required for
this authorized campaign. Paid fallbacks, secret exposure and private research
disclosure remain outside scope.

## Historical execution boundary and next steps

Automatic approval review rejected earlier broad local test executions after
Google generative-language endpoint traffic. Even blank credentials/offline
environment flags did not establish absence of external requests. Those runs
are not passes. Do not repeat them or move the same execution to hosted CI to
circumvent the rejection. External model tests need informed user authorization
for the payload and destination, or a materially safer independently enforced
execution boundary.

The review branch is outside all existing push-trigger branch filters. Creating
this checkpoint does not dispatch workflows. PR #81's branch automatically runs
the live trading gate on push, so promoting these changes there would itself
start external model execution. No promotion, merge or deploy is claimed here.

After resolving the execution boundary: verify the runtime repair, integrate the
reviewed changes without overwriting other work, run exact-revision full gates,
inspect one real Max receipt, then continue the broader handoff's shared-state,
hypothesis lifecycle, recursive research, held-out evaluation, durable storage,
executor and deployed end-to-end acceptance. Whole-app completion remains open.
