# Research runtime: budgets, recovery, memory and tools

This extends PR #79's real specialist stage. It is an implementation, not a
measured claim that multiple workers outperform a strong single model.

## Durable research jobs

Capability-protected background jobs, synchronous research and QUICK chat now
use an SQLite runtime in the existing
private data root. Schema creation is automatic; no paid database or additional
package is required. Keep this database on a local filesystem with SQLite locking.

Checkpoints cover discovery, enriched full-text evidence, each worker's raw
provider envelope, numeric tool outputs, chief/lab output and the final result.
Data/model types, input hashes, code hashes and output checksums are verified on
replay. A completed stage is reused. A stage with an ambiguous external side
effect is blocked pending reconciliation rather than blindly replayed.

The existing exclusive job-runner process lock remains. On restart, its interrupted
stages become resumable. Explicit resume is limited to three attempts, the same
code/input/budget contract and the original one-hour run deadline. Changing code
or inputs requires a new run; resume cannot reset spent quota. An unfinished
read/reasoning stage may repeat after interruption and can consume additional
reserved calls. Hosted generation is not claimed to be exactly reproducible.

At most 2,000 runtime records are retained. Checkpoints expire six days after
their original execution deadline; expired records are pruned when another run
starts. Stage payloads are capped at 16 MB each, with a shared 256 MiB UTF-8
payload ceiling (`RESEARCH_CHECKPOINT_BYTES`). This is not total filesystem usage:
SQLite metadata, WAL, memory records and archived job results need separate host
capacity. Cancellation also blocks late checkpoint completion.

Endpoints, using the existing `X-Research-Job-Token` header:

- `POST /api/v1/research-jobs/{job_id}/cancel`
- `POST /api/v1/research-jobs/{job_id}/resume`
- `GET /api/v1/research-jobs/{job_id}/progress` includes durable events and limits.

The UI exposes stop and resume. Cancellation prevents new reservations and stage
starts. An already dispatched provider request may continue until its timeout;
its completion cannot change a cancelled job into completed. No instant remote
provider cancellation is claimed.

## Shared application ceilings

Before each generation attempt, including retries, all participating processes
reserve from the same transactionally updated budget. Gemini SDK retries are
disabled within this runtime so retry dispatch is controlled by the app. Provider
output limits are enforced at 6,000 tokens. Unknown/failed attempts are not refunded.

Per run: up to four HTTP attempts per logical call, 2,000,000 input UTF-8 bytes per
logical call, and 6,000 output tokens reserved per allowed attempt. These are
resource ceilings, not recommended model sizes or statistical success thresholds.

Operator environment settings (no secrets):

```dotenv
RESEARCH_PROVIDER_HTTP_PER_HOUR=120
RESEARCH_PROVIDER_INPUT_BYTES_PER_HOUR=24000000
RESEARCH_PROVIDER_OUTPUT_TOKENS_PER_HOUR=720000
RESEARCH_COMPANY_CONCURRENCY=4
```

Provider windows are UTC epoch hours and shared across projects, keys and workers.
They are conservative application caps, **not a provider quota/billing oracle**.
The existing confirmed-zero-cost guard still decides eligibility. Actual input
token counts and billed/used output tokens remain UNKNOWN when provider receipts
do not provide them; input bytes must never be presented as measured tokens.
All public research and QUICK chat routes establish this context. QUICK chat has
four HTTP attempts, 2 MB of input bytes, 24,000 reserved output tokens and five
minutes; local small talk may use zero requests. Raw programmatic adapter calls
outside these application entry points do not inherit a runtime. Provider metadata
discovery requests are separate from these generation-attempt counters.

## Governed memory and source corrections

Private project endpoints use the existing `X-Project-Token` header:

- `GET /api/v1/projects/{project_id}/research-memory`: inspect/export JSON records.
- `POST` to the same endpoint: add a typed user-supplied unverified record.
- `PUT /api/v1/projects/{project_id}/research-memory/{record_id}`: validate then
  atomically correct a record, increment revision and invalidate consumers.
- `DELETE /api/v1/projects/{project_id}/research-memory`: clear governed records,
  legacy project research notes, graph hints and project concept hints. Stop active
  research first. Original uploads, canonical job archives and backups remain.
- `DELETE /api/v1/projects/{project_id}/research-memory/{record_id}`: delete a
  governed record and its derived runtime checkpoints. Active research must stop
  first. Canonical job archives/original uploads/external backups are separately
  retained; this is **not account-wide erasure**.
- `POST /api/v1/projects/{project_id}/source-corrections` with `source` and `reason`:
  invalidate registered dependent runs and memories in this project. Result API
  reads then return an unresolved reassessment notice instead of the old strong
  answer. Exact source references must match the registered URLs.

Memory separates record kind, trust, source references, revision, creation and
expiry. Generated text stays GENERATED_UNVERIFIED. Records require revalidation
after 30 days; each project is capped at 1,000 records. Runtime memory is quoted as
untrusted context. Concept hints created inside durable jobs are project-scoped.
The UI's memory button exposes inspect, export, add, correct and delete. Memory
consumption records the exact revision; correction/deletion propagates through
downstream research-memory consumers, not just the answer that created a record.
Project hints are evicted on corrections. The single-record delete endpoint does
not erase all legacy notes; use the project-memory clear endpoint for those.
Public research consumes governed summaries, whose revisions can be invalidated;
the legacy graph remains inspectable but its untracked answer summaries are not
fed back into this runtime. Concept names remain unverified search leads.
Existing session capabilities remain tab-scoped, so export before losing a session.

## Actual tools and artifacts

Validation/implementation workers may request up to two bounded numeric tools.
The registry checks role, exact argument fields, effects and sizes outside the
LLM. The existing numeric AST interpreter permits arithmetic/loops with operation
limits; it has no filesystem, network, imports or subprocess primitives. Receipts
include code/input/output hashes, environment version, stdout/error class, exit
status, timestamps and a downloadable JSON artifact. Failed execution has no
invented result or artifact. Successful arithmetic does not establish scientific
model adequacy or a physical/clinical observation.

A private user endpoint also runs approved numeric tools and returns JSON artifacts:

```json
{
  "tool": "numeric",
  "call_id": "compound-interest-example-v1",
  "arguments": {
    "code": "result = principal * (1 + rate) ** years",
    "inputs": {"principal": 100, "rate": 0.05, "years": 2}
  }
}
```

Send to `POST /api/v1/projects/{project_id}/tools/execute`. Role/effects are fixed
by server code. Arbitrary Python/native code and general application builds are
not enabled: this host has no approved general isolation backend. The numeric
interpreter is not mislabeled as a general Python/container runtime.

## Task contracts and evaluation

Research runs preserve the original request, explicit numbered parts, recognized
deliverables, task types, freshness, resource settings and a bounded dependency
graph. Unrecognized coverage stays NOT_ASSESSED. The compiler is a deterministic
heuristic, not a guarantee of perfect language interpretation. Existing detailed
coverage/claim gates still determine the answer state.

`utils/paired_evaluation.py` compares supplied independently graded baseline and
candidate receipts against a frozen manifest. It rejects changed/tuned holdouts,
missing pairs, duplicate trials and unequal HTTP/time allocations. It clusters
bootstrap uncertainty by task, preserves missing metric denominators and reports
task failure tails. FIXTURE, RECORDED_REPLAY and LIVE remain separate. A numerical
score does not establish independent grader validity or scientific truth.
Mixed execution campaigns or different paired grading methods are rejected.
Latency is lower-is-better; missing pairs and task-weighted baseline/candidate
means are explicit. HTTP/time matching alone does not prove equal token spend or
hardware. Unchecked explicit task parts remain PARTIAL and appear in the UI.

No representative live model comparison, OCR ground-truth evaluation, hardware
load measurement or clinical/physical experiment was performed here. Before
superiority claims, freeze representative tasks/holdout/graders and run both
matched-budget and deployment-budget comparisons on confirmed-free models.

## Reproducible validation

```bash
python -m unittest discover -s tests -p test_research_runtime.py -v
python -m unittest discover -s tests -p test_paired_research_evaluation.py -v
python -m pytest -q tests/test_governed_research_tools.py tests/test_runtime_job_integration.py
python scripts/run_foundation_gate.py
```

The first two suites run without external model/network dependencies. They use
real SQLite files and competing child processes plus explicitly synthetic
evaluation fixtures. Other suites require the repository dependencies. Local
dependency installation was blocked by network approval; those checks must be
verified by the exact revision's existing CI. Current receipts are recorded in
PR #79, including failures; old green checks never certify new untested code.
