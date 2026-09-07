# Isolated builds and controlled improvement

The existing research company can request `isolated_build` through the typed
tool registry. Only validation, implementation and supervisor roles have that
effect. Python and Node source bundles run in fresh local Linux containers,
then return a downloadable ZIP containing supplied source and generated files.
The project tool endpoint uses the same executor and fixed server-owned role.
It never executes a generated program directly on the application host.

## Operator setup

This feature is disabled until a local Linux Docker daemon and reviewed runtime
images are available. Use a dedicated executor host or appropriately configured
rootless Docker with working resource controls. A shared kernel is not a proof
of universal isolation. Docker access is an operator privilege; never mount its
socket into generated-code containers or expose it to the browser/model.

Provision images outside the application. Python images need `python3`; Node
images need both `python3` (the controller) and `node`. The CI fixture Dockerfile
shows a reproducible provisioning procedure, with the resulting content ID
recorded in execution receipts. It is a test image, not a universal dependency
environment. The application neither pulls images nor installs dependencies.

Set private server configuration:

```text
INFINITY_BUILD_EXECUTOR=docker
INFINITY_DOCKER_SOCKET=unix:///var/run/docker.sock
INFINITY_PYTHON_IMAGE=sha256:<reviewed-local-image-id>
INFINITY_NODE_IMAGE=sha256:<reviewed-local-image-id>
```

Mutable tags, remote sockets, missing images and missing Linux resource controls
are rejected. The existing Railway web deployment is not assumed to provide a
Docker daemon. Windows execution requires a separately configured Linux Docker
environment and target-host validation; that was not performed here.

Example authorized project tool request (send the existing project capability
in `X-Project-Token`, not in a URL):

```json
{
  "tool": "isolated_build",
  "call_id": "build-unique-id",
  "arguments": {
    "runtime": "python",
    "entrypoint": "main.py",
    "files": {
      "main.py": "from pathlib import Path\nPath('index.html').write_text('<h1>My app</h1>')"
    }
  }
}
```

POST to `/api/v1/projects/{project_id}/tools/execute` (under the existing API router
prefix). Files in `/inputs` are read-only; write outputs to `/work`. Limits:
64 input files, 512,000 input bytes, 64 output files, 2,000,000 output bytes,
64,000 log bytes, 30 seconds, 256 MiB RAM, 32 processes and one CPU. At most two
containers are leased globally per application data store. The container has
no network, inherited host secrets, Docker socket or arbitrary host mounts;
root filesystem is read-only, capabilities are dropped, no-new-privileges and
an explicit seccomp filter apply. Resource values appear in the receipt.

Timeouts, failed programs, excessive output, invalid paths, unsafe artifacts
and unconfirmed cleanup cannot return an EXECUTED artifact. Expired leases are
reconciled on the next executor invocation; ambiguous deletion retains the slot.
A killed application controller therefore needs the next invocation/operator
cleanup; this is not a separate always-running container janitor.

`EXECUTED` records software execution, not correct science, safe deployment,
clinical validation or a usable application by itself. Generated files remain
untrusted; the web UI downloads ZIPs and never renders generated HTML inline.

## Failure to proposal to protected trial

The public research manager records observed worker failures, malformed report
contracts, incomplete plans, blocked tools and missing deliverables as bounded,
idempotent proposals. Proposals contain categories, counts and hashes, not raw
questions, source content, provider errors or secrets. They appear in Process
and at the capability-protected
`GET /api/v1/projects/{project_id}/improvement-proposals` endpoint. Proposal text
is a next action, not a claim that the underlying cause was proven.

Candidate implementations are supplied as reviewable source bundles. They are
never applied to production automatically. The operator configures a protected
suite file and its exact raw SHA-256 commitment:

```text
INFINITY_IMPROVEMENT_SUITE=/private/path/final-cases.json
INFINITY_IMPROVEMENT_SUITE_SHA256=<sha256-of-file>
```

The JSON suite has schema 1, `provenance` set to `SYNTHETIC` or
`OPERATOR_HELD_OUT`, and 3..6 cases. Each case has `id`, `group` (`target`,
`regression`, `safety`), `input`, and `expected`. Every group is mandatory.
Use separate development cases to design the candidate. Final-case labels are
host-only; the container receives only the current input in `/inputs/case.json`
and must write a JSON result to `/work/answer.json`. The grader stays in the
host process and performs strict exact JSON comparison, rejecting duplicate
keys and nonfinite values. Candidate-supplied pass flags are irrelevant.

```sh
python scripts/run_improvement_evaluation.py --project PROJECT --proposal ID \
  --baseline baseline-bundle.json --candidate candidate-bundle.json
```

Both bundle files have `runtime: "python"`, `files` and `entrypoint`. Their pair
hash is frozen before final data are opened; the existing HoldoutVault records
the dataset/protocol commitments and final receipt. SQLite reserves each suite
and case globally before any execution. Reuse after failure/crash is rejected;
renaming/reordering the same cases cannot make a fresh holdout. These small
commitments are retained intentionally across proposal retention.

The baseline and candidate each execute twice per case with the same immutable
image and limits. Order alternates by case. The receipt includes actual timings,
input/artifact hashes, cleanup, outcomes, denominators and reproducibility.
A conditional pass requires a reproduced target failure fixed by the candidate,
passing regression/safety cases, no previously passing case regression, repeated
outputs and confirmed cleanup. This is a scoped software result. It is not a
statistical population claim or a measured improvement in live AI answers.
The suite owner's independence and semantic adequacy still require review.

No trial can modify production source, grader, release checks, permissions,
spending policy or deployment. Rollback remains the existing versioned Git/PR
process because the app does not install candidate changes. For model-quality
campaigns use the existing frozen manifest and paired evaluator with independent
grading and representative data; do not reuse these synthetic software cases.

## Hypothesis plans

Specialist drafts now preserve mechanisms, assumptions, source references,
applicability boundaries, variables with units/roles, controls, confounders,
baseline, outcome/decision thresholds, power assumptions, analysis/uncertainty,
stopping rules, failures and replication/environment details. Missing values
stay UNKNOWN/TO BE ESTIMATED. Inapplicability needs an explicit reason; truncated
critical fields keep the plan incomplete. A structurally complete plan remains
TEST_PROPOSED / INCONCLUSIVE with semantic adequacy and novelty NOT_ASSESSED.

## Validation scope

`test_isolated_build_runtime.py` has local contract checks and a separately
enabled real-container lane. `test_improvement_runtime.py` includes real
baseline/candidate runs, a regression rejection and one-use holdout checks.
The Foundation workflow provisions its test image and requires both lanes to
pass. Default offline runs skip the real-container cases; a skipped test is
not evidence of execution. Exact revision run results are recorded in PR #79.

Docker primary references: [container run](https://docs.docker.com/reference/cli/docker/container/run/),
[rootless mode](https://docs.docker.com/engine/security/rootless/),
[daemon access](https://docs.docker.com/engine/security/protect-access/),
[seccomp](https://docs.docker.com/engine/security/seccomp/).
