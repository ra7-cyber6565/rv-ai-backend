# Astra continuation handoff — 2026-09-14

This note is a **truth-preserving continuation aid** for the next Astra/ChatGPT work session. It does not claim product completion. Read `AI_HANDOFF.md`, `MAX_MODE_CONTRACT.md`, and this file before making changes.

## 1. Current repository/release truth

- Repository: `ra7-cyber6565/rv-ai-backend`
- Current `main` observed at the start of this audit: `831dbc7209253e58bbfa0ec79b9efe8e130bf523` (`Update handoff after unified Max merge and production deploy`).
- Unified Chat/Max implementation was merged earlier in PR #80 via merge commit `19ae77a7c0ce8a3eef7ce5b43073e2ea52e97249`.
- Public user modes remain exactly:
  - Chat -> `QUICK`
  - Max -> strongest bounded `MAXIMUM`
- Do not add a duplicate public Company/Marathon mode. Keep legacy names backend-compatible only where already required.
- Hard constraints still apply: **₹0 only**, no silent paid fallback, preserve user data, do not move heavy setup to the user's laptop.

## 2. CI status: do not overclaim exact-head verification

For current `main` SHA `831dbc7209253e58bbfa0ec79b9efe8e130bf523`, GitHub reported only two check-runs during this audit:

- `anti-confirmation-attestor` — success
- `offline-regression` — success

The five-gate suite recorded in the older handoff belongs to the earlier validated PR/merge head. Do **not** state that all five gates have run on `831dbc...` unless they are explicitly rerun on that exact revision (or a later exact integrated revision) and receipts are recorded.

## 3. Railway production state observed on 2026-09-14

Railway project:

- project: `desirable-learning`
- production environment id: `a911dd49-980f-4722-a6d8-b6c176d1c439`
- service: `web`
- service id: `3593244e-5f06-42a3-987b-addf4440833e`
- public domain: `web-production-0dd45.up.railway.app`
- source: `ra7-cyber6565/rv-ai-backend`, branch `main`
- start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- latest deployment observed: `3d003d52-e234-473f-bc9d-f5adec492bfc`, status `SUCCESS`

The deployed service currently showed **no attached volume**.

### Important staged Railway patch — NOT DEPLOYED

Production currently has a staged Railway patch:

- patch id: `016d0daa-b61f-4966-a424-43c17b6fdad5`
- patch status: `STAGED`
- change count: 3
- staged volume mount: `data`, `5120 MB`, mounted at `/data`
- staged variable name includes: `INFINITY_DATA_ROOT`

Do **not** blindly accept/deploy this patch.

Reason: the user requires strict ₹0 operation. Railway's current public pricing/limits need to be checked against the user's actual plan before applying a 5 GB volume. A Free plan only allows 0.5 GB volume storage, while 5 GB is a Hobby-tier ceiling, and volume usage is metered. If the account plan/cost cannot be verified as compatible with the user's ₹0 rule, either reduce/rework the persistence plan to a genuinely free-compatible option or leave this patch staged.

## 4. Persistence failure is now practically reproduced

A real production research job on 2026-09-10 used job id:

`637831e4d93e493eabf0651bc07336cd`

Railway logs show:

- `POST /api/v1/research-jobs` -> `202 Accepted` at ~10:22:57Z
- repeated job/progress polling returned `200`
- `GET /api/v1/research-jobs/637831e4d93e493eabf0651bc07336cd/result` -> `200 OK` at ~10:31:46Z

On 2026-09-14, fetching the same result URL returned:

`{"detail":"Research job nahi mila"}`

This is strong operational evidence that the currently deployed job/result state is not durable across the service lifecycle. Treat production persistence as **open and reproduced**, not theoretical.

An earlier job `f7fecd13c86b45bd801ac7b1d35a6ecf` was being polled immediately before a server process restart in the same log window, which reinforces the need for restart/restore testing after persistence is fixed.

## 5. Production warnings seen during the real run

The successful research run emitted non-fatal warnings/errors including:

- Chroma/telemetry-like events: `capture() takes 1 positional argument but 3 were given`
- Transformers warning: `TRANSFORMERS_CACHE` is deprecated; use `HF_HOME`

These did not prevent the later `/result` 200 response, but they should be triaged separately. Do not conflate them with the persistence failure.

## 6. What the September 10 run does and does not prove

It proves that a production research job could be accepted, polled, and eventually return a result on the then-running instance.

It does **not**, from the retained evidence alone, prove all of the following:

- that the submitted mode was the unified user-facing `MAXIMUM`
- that all six specialist workers actually executed
- that the chief executed
- that the output passed a held-out quality benchmark
- that receipts survived a restart/redeploy

The original result is no longer retrievable, so do not retroactively promote it into durable Max/worker acceptance evidence.

## 7. Safe continuation order

Follow this order and record receipts for each step:

1. **Resolve persistence without violating ₹0**
   - Determine the user's actual Railway plan/cost status if possible.
   - Do not deploy the existing 5 GB staged volume until its cost/limit is compatible with the ₹0 rule.
   - Prefer the smallest safe persistent capacity actually required for SQLite/job receipts rather than assuming 5 GB.

2. **Persistence restart/restore proof**
   - After a safe persistence deployment, create a test job/state record.
   - Record job id and exact deployment/revision.
   - Restart/redeploy in a controlled way.
   - Prove job metadata/result/checkpoints can still be fetched after restart.
   - Record before/after receipts.

3. **Exact revision identity + CI**
   - Identify the exact Git commit deployed after any code/config change.
   - Run/record the required exact-head gates for that exact revision; do not inherit receipts from an older SHA.

4. **Zero-cost provider readiness**
   - Prove the provider route is eligible/confirmed free at run time.
   - No silent paid fallback.

5. **Live unified Max acceptance**
   - Submit through the same public Max path a real bounded `MAXIMUM` request.
   - Capture request mode, job id, progress stages, final result, exact revision/deployment, elapsed time, and error/fallback receipts.

6. **Six-worker + chief proof**
   - Where the confirmed-free model layer is usable, require evidence for all specialist roles:
     `evidence`, `validation`, `mechanism`, `red_team`, `data_quality`, `implementation`.
   - Record chief synthesis receipt separately.
   - If provider is unavailable, fail soft and mark worker/chief proof pending. Never fake the receipts.

7. **Held-out benchmark**
   - Run a representative set of unseen queries with measurable extraction/claim/citation/contradiction quality criteria.
   - Keep benchmark data and scoring separate from implementation prompts to reduce confirmation bias.

8. **Production executor proof**
   - Validate the isolated executor on a production-compatible off-laptop host.
   - Record exact revision, sandbox/tool versions, resource limits, timeout behavior, and output receipts.

9. **Hard E2E + requirement ledger closure**
   - Revisit every `PARTIAL`, `MISSING`, or `BLOCKED` requirement in `docs/INFINITY_REQUIREMENT_LEDGER.md`.
   - Close only with explicit receipts; otherwise keep the status conservative.

## 8. Still-open product acceptance areas

At the end of this audit, continue to treat these as open until newly proven:

- durable production persistence + restart/restore
- live unified Max answer-quality acceptance
- live six-worker/chief execution receipts
- independent held-out quality/extraction benchmark
- production-compatible isolated executor proof
- hard E2E research acceptance
- residual requirement-ledger closure

## 9. Anti-regression rules for the next agent

- Preserve the unified Chat/Max UX.
- Do not duplicate already-merged architecture.
- Passing CI is not the same as live production acceptance.
- A successful HTTP response is not sufficient evidence of six-agent execution or answer quality.
- Do not claim persistence until a restart/restore test passes.
- Do not accept the staged 5 GB Railway volume until the ₹0 constraint is verified.
- Do not use old job/result receipts as if they survived; the September 10 result currently does not.
- Keep `AI_HANDOFF.md`, `WORK_STATUS.md`, and the requirement ledger synchronized after each material milestone.

## 10. Immediate next action

The highest-value next action is **not another feature build**. It is to settle a zero-cost-safe persistence configuration, deploy it only with explicit authorization and cost safety, then execute a restart/restore proof. Once persistence is durable, new Max/worker/benchmark receipts become worth collecting because they will survive the service lifecycle.
