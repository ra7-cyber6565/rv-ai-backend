# AI Company research

The existing source discovery, document/PDF reading, citation checks, safe numeric
lab, hypothesis rejection and final quality gates now have an optional production
specialist stage. The previous ScientistSociety primitives alone did not dispatch
specialists from the main question-to-answer path.

## Modes and actual budgets

| Mode | Specialist first passes | Chief budget | Total logical-call ceiling |
|---|---:|---:|---:|
| COMPANY | 4 | 4 | 8 |
| COMPANY_PLUS | 6 | 4 | 10 |

Select **AI Company · 4** or **Company+ · 6** in the existing web app. API clients
can send either mode to the existing capability-protected `/api/v1/research-jobs`
endpoint. `/api/v1/depth-modes` exposes the same limits. Prefer background jobs
for these long runs. Existing QUICK, DEEP, MAXIMUM, MARATHON and CUSTOM budgets
are preserved; arbitrary CUSTOM input cannot enable unlimited workers.

Both presets retain Marathon's bounded retrieval: up to five search rounds,
40 ranked sources and 16 legally accessible full texts, including books/PDFs
when available. These are ceilings, not a promise to retrieve/read every item.
All specialists receive the same already-retrieved, guarded corpus. This feature
does not claim separate literature searches or independent scientific evidence
from each specialist.

## Execution

1. Existing source discovery and reading build the evidence pack.
2. Evidence, validation, mechanism and red-team specialists receive separate
   first-pass task packets without seeing peer answers. Company+ adds data
   quality and implementation specialists.
3. Each specialist runs one logical generation through the existing provider
   router. Child processes isolate SDK global configuration. Up to four workers
   run concurrently; six workers run in bounded batches.
4. Structured reports carry source-linked claims, testable hypotheses, simpler
   baselines, falsification conditions and limitations. Unsupported claim labels,
   unknown cited source IDs and incomplete hypothesis records produce gaps.
5. The chief receives the quoted drafts as untrusted analysis. It compares them
   with the original sources, resolves or preserves contradictions, deduplicates
   ideas, explains rejected/modified hypotheses and identifies next tests.
6. Existing critique, hypothesis parsing, safe lab and final completion gates
   still run. A missing/invalid specialist is a missing reasoning pass. A useful
   partial answer cannot silently become a completed company run.

The **Research process** tab shows worker reports. The structured record is at
`verification.research_company`. This record is preserved in normal durable job
results; the existing size-limited storage can compact unusually large reports.
Each worker has an ID, UTC start/end times, input/output hashes, a logical-call
reservation, router accounting and an artifact reference to its bounded raw
response. Assumptions, contradictions and remaining questions survive the chief
handoff. Public research now binds a durable SQLite runtime; events and completed
worker/provider/tool stages survive an interrupted job. See
`RELIABILITY_RUNTIME.md` for input/code binding, original-deadline resume,
cancellation and limits. Direct standalone calls without that context retain
only their in-memory/final-report events.

## Truth and usage boundaries

- Role count is not model count. All roles may use the same configured model.
  Distinct models and scientific replication remain explicitly unverified.
- A source ID's existence does not prove that the source supports the claim.
  Worker claims have `entailment_verified: false`; chief/final evidence checks
  remain necessary. Worker drafts do not create new source evidence.
- Worker hypotheses are **INCONCLUSIVE / TEST_PROPOSED**. Workers cannot promote
  themselves to experimental PASS, even if their generated JSON requests it.
  Validation/implementation workers can request bounded numeric execution through
  the server-controlled registry; actual receipts stay distinct from proposed tests.
  In-vitro, animal,
  clinical, manufacturing and other physical validation are not performed by
  these text workers. A drug research hypothesis is not an established cure.
- Company workers force confirmed-zero-cost routing. No eligible model yields
  a zero-call unavailable result. The chief also checks eligibility before
  entering generation, including the legacy no-backup SDK route. A local model
  is still hardware dependent.
- Each process has a 180-second deadline and is terminated on timeout. No raw
  exception/provider body is forwarded. Usage after a killed process can be
  unknown: totals become explicit lower bounds with a missing-receipt count.
- Logical call limits include specialists and chief. HTTP retries can exceed
  that count. Provider quota, cost dashboards and peak RAM are not inferred
  from the number of workers.
- `RESEARCH_COMPANY_CONCURRENCY=1..4` caps simultaneous workers (default 4).
  Set a lower value on constrained hosts. SDK process isolation costs RAM;
  process-local cooldowns are not shared between workers. Atomic application
  budgets are shared across processes/projects; restart recovery reuses completed
  checkpoints under the same code, inputs, limits and original deadline.
- Handoffs allot bounded space to every specialist. Very long drafts may be
  clipped for the chief; that leaves a missing handoff pass and prevents a
  complete-review claim. The available original worker report remains in the
  structured result subject to durable-storage limits.

## Validation and remaining evidence

`tests/test_research_company.py` exercises simultaneous execution, peer isolation,
same-model honesty, invalid citations/labels, experimental-status coercion,
incomplete hypotheses, timeouts, secret redaction, total accounting, prompt-data
boundaries, the actual chief pass pipeline, API budgets/private job submission,
and an actual child process with no confirmed models.

These software tests use fixture model outputs. They do not measure whether four
or six specialists improve answer quality over a strong single agent. Before a
quality/superiority claim, run a frozen paired benchmark across representative
questions, blind the graders, match logical/HTTP/time budgets, keep an untouched
test set, report effect sizes and uncertainty, and examine failure tails.
Remove or revise roles that add no practically meaningful benefit after an
adequately powered ablation; non-significance alone is not proof of no benefit.

Live confirmed-free provider tests, RAM/latency load tests on the deployment host,
cross-model comparison, independent retrieval per worker, targeted second-pass
retrieval and real external experimental replication remain separate work.
No universal problem-solving, scientific discovery or 100/100 maturity claim is
established by this implementation.

## Runnable validation

The existing live gate now accepts both company modes and requires actual worker
and chief execution receipts. Merely printing four role headings cannot pass it.
On the existing Windows installation, after checking out the reviewed version:

```powershell
.\RUN_LIVE_ZERO_COST_GATE.ps1 -DepthMode COMPANY -DataRoot "D:\InfinityResearchAI"
.\RUN_LIVE_ZERO_COST_GATE.ps1 -Execute -DepthMode COMPANY -DataRoot "D:\InfinityResearchAI"
```

The first command is preflight only. The second performs live work only when
confirmed-zero-cost prerequisites pass. Use `COMPANY_PLUS` for six workers. This
document records runnable commands, not a claim that either live run occurred.
The complete 22-part specification audit and 18 acceptance-case mappings are in
`docs/INFINITY_REQUIREMENT_LEDGER.md`.
