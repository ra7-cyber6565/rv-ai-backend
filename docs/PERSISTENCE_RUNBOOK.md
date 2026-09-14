# Production persistence runbook

This runbook is intentionally conservative. It describes how to deploy and
**prove** durable Infinity Research AI state without silently moving large
rebuildable caches onto persistent storage.

Do not treat this document as authorization to change production. Verify the
provider plan/cost first and obtain explicit deployment approval.

## Storage modes

### Legacy/unified mode

Existing installs can keep using either:

```text
INFINITY_DATA_ROOT=<one writable root>
```

or the older compatible alias:

```text
INFINITY_WORK_ROOT=<one writable root>
```

All app state, model/cache files, temp files, and logs stay under the one root,
matching historical behavior.

### Split production mode

Cloud deployments with a constrained persistent volume can opt in to:

```text
INFINITY_DURABLE_ROOT=/data
INFINITY_EPHEMERAL_ROOT=/tmp/infinity_ai
```

`INFINITY_DURABLE_ROOT` owns state whose loss can invalidate research/job
receipts:

- `archive/`
- `knowledge/`
- `research_memory/` (including research-job metadata/results)
- `uploads/`
- `vector_db/`

`INFINITY_EPHEMERAL_ROOT` owns rebuildable/runtime-heavy data:

- `cache/`
- `logs/`
- `models/`
- `temp/`

In split mode Hugging Face, Transformers, sentence-transformers, Torch, XDG
cache, and OS temp locations follow the ephemeral root. Existing persistence
quota guards still resolve the configured durable root.

## Pre-deploy safety gate

Before changing production, record all of the following:

1. exact Git commit intended for deployment;
2. exact CI results for that commit;
3. current provider plan and persistent-volume limits/cost;
4. confirmation that the selected storage configuration is compatible with the
   project's strict zero-cost rule;
5. existing production environment/volume state;
6. rollback path.

Do not deploy a large staged volume merely because it exists in the provider
configuration. A staged configuration is not evidence that it is free or safe.

## Production configuration target

When a zero-cost-compatible persistent mount is available, mount only the
persistent volume at the durable root and keep the ephemeral root on normal
container filesystem storage.

Example layout (paths are illustrative; use the host's real mount path):

```text
persistent volume -> /data
INFINITY_DURABLE_ROOT=/data
INFINITY_EPHEMERAL_ROOT=/tmp/infinity_ai
```

Do not simultaneously set a legacy `INFINITY_DATA_ROOT` to the persistent
volume unless there is a deliberate reason to return to unified storage; doing
so makes the legacy root available to components that are intentionally kept
rebuildable in split mode.

## Restart/restore acceptance proof

Persistence is not complete until this test passes on the deployed revision.

1. Record deployment id and exact Git SHA.
2. Submit a bounded test research job through the normal public API.
3. Record the returned job id.
4. Wait for terminal completion and fetch its result.
5. Record a sanitized digest/identity of the result and relevant job metadata.
6. Perform a controlled service restart/redeploy **without deleting the
   persistent volume**.
7. After the new instance is healthy, fetch the same job id and result again.
8. Verify the job/result identity matches the pre-restart receipt.
9. Verify the public storage health endpoint reports durable storage available
   and does not expose filesystem paths.
10. Record the post-restart deployment id, exact Git SHA, and receipts.

A `200` result before restart alone is not a persistence proof. If the same job
cannot be recovered afterward, keep persistence acceptance open.

## Interrupted-job honesty

The current job runner can preserve completed durable results, but Python work
that was actively running at process death cannot magically resume. Persisted
queued/running work may reload as interrupted. Do not report that as successful
resume support unless a separate checkpoint/resume mechanism is implemented and
proven.

## Rollback

If the deployed revision or split configuration causes regressions:

1. do not delete the persistent volume or job/result files;
2. restore the last known-good application revision/configuration;
3. keep a receipt of the failed deployment and error;
4. only migrate or delete durable data through an explicit, tested migration or
   retention procedure.

## After persistence is proven

Only then collect durable evidence for the remaining acceptance gates:

- real public `MAXIMUM` run;
- six specialist worker receipts and chief synthesis when a confirmed-free
  provider is usable;
- held-out answer/extraction benchmark;
- isolated executor production proof;
- hard end-to-end research acceptance;
- remaining requirement-ledger closure.
