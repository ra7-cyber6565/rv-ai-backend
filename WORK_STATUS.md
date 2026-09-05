# Infinity Research AI — Master Work Status

This file is the coordination source of truth for multi-agent work.

## Independent audit update — 2026-08-28

- Production `main` audited at `8c8ee5fe8cb3b4644b52eb644904267156494300`;
  Foundation CI was green with 2,007 pytest tests, API smoke 42/42,
  cross-domain 649/649 and superconductivity 156/156.
- PR #62 remains **UNMERGED / NOT ACCEPTED**. Its large maturity wave is
  substantial standalone code, but most modules are not yet invoked by the
  production question-to-answer path. Passing unit tests are not production
  wiring proof.
- Capability 14 (Formal Logic) and 112 (Capability Discovery) now require a
  revision-bound `production_wiring` receipt; CODE+TEST alone cannot mark them
  VERIFIED.
- Dark-matter acceptance is now a mandatory Foundation receipt stage. The
  newly enforced run exposed and closed the DM-05 warning-token regression;
  current offline result is 328/328, 18/18 closed.
- The post-deployment validator now rejects NaN/infinity with a domain-level
  `must be finite` error before canonical receipt hashing.
- Exact current PR-head GitHub CI is still the merge authority. Claude's local
  Windows worktrees/stashes have not been read, applied, popped, reset or
  overwritten by this branch.

## Hard rules

- ₹0 only. No paid API/model/service, no silent paid fallback, no surprise billing.
- Secrets stay out of GitHub and Android APK. Backend env/private secret store only.
- Do not bypass paywalls/copyright/access controls.
- Human-first answer: easy Hinglish explanation first; sources/access depth/audit/errors later.
- Fact / Evidence / Inference / Hypothesis / Speculation / Unknown must remain distinct.
- `ESTABLISHED`/strong-fact language requires strong evidence and appropriate access depth.
- Foundation first; advanced discovery features begin only after the foundation gates really pass.
- Claude and ChatGPT must not edit the same ACTIVE task/files at the same time.

## Architecture target

Question -> Research Planner -> domain identification -> query expansion -> multi-source discovery -> retrieval -> document/media processing -> evidence extraction -> relevance/source-quality/contradiction checks -> multi-angle reasoning -> hypothesis generation -> criticism/falsification -> verification/math/simulation where possible -> synthesis -> human-first answer -> technical audit.

Storage target: GitHub = code/version history; laptop D: = bounded fast runtime/working storage; Google Drive = temporary optional archive; TeraBox = optional later archive only after official zero-cost API approval. Remote upload must be verified before any local deletion.

## ChatGPT scope — do not shrink

ChatGPT owns final integration/reliability, independent audit of Claude work, evidence correctness at the system boundary, ₹0/provider safety, large-file/storage lifecycle, async durability, security, integrated regression and final architecture review. After foundation passes, ChatGPT also owns the Advanced Scientific Discovery Engine work listed below.

## AI Company integration — ChatGPT, 2026-09-05

- Isolated branch: `codex/research-company-20260905`, based on main
  `1d7eddaca3e5146184cfa4e1884c8dbc3564f84e`. Exact base Foundation Actions
  run `33852832167` passed before advanced integration began.
- COMPANY / COMPANY_PLUS connect 4 / 6 real specialist worker invocations to
  the existing chief, evidence checks, lab and completion gates. Shared corpus,
  separate first-pass contexts, bounded process isolation, zero-cost routing,
  typed draft validation and aggregate usage receipts. Existing presets retain
  their budgets. Web/API expose both new modes and worker reports.
- Focused fixture tests have passed during development; the commit's full
  offline gates and live confirmed-₹0 validation remain separate required
  evidence. Do not call this empirically superior or release-ready from fixtures.
- Initial broad local tests were blocked after an outbound Google endpoint
  attempt. Subsequent validation uses blank credentials and an inherited
  socket-level network denial. Clean-checkout attestors require committing
  source edits before integrated validation.
- See `docs/AI_COMPANY_RESEARCH.md` for exact limits, deployment considerations,
  test scope and remaining benchmark/independent-retrieval work.
- PR #79 first exact head passed AI-1, AI-2, model-reality and anti-confirmation
  CI; Foundation found stale browser source-pattern assertions (4112 full-suite
  tests passed, one failed). Checks now cover the explicit three long modes,
  unchanged deadline/stall limits and both company + existing progress panels.
  Local native SDK traffic is blocked by a fail-closed kernel syscall filter;
  earlier Python-only isolation did not block that native path.
- Existing PRs #63/#65 and other contributors' branches were not merged or
  overwritten. No local Windows changes or external receipts were touched.

## Active foundation status

| Task | Owner | Status | Notes |
|---|---|---|---|
| Windows live ₹0 gate + launcher hardening | ChatGPT | FULL FOUNDATION CI PASS | PowerShell runner accepts only non-secret data-root/receipt arguments; preflight probes an absolute writable out-of-repo root and minimum free space before any provider call. Live crashes produce sanitized receipts, and backend startup is repo-relative instead of hard-coded to one `C:\Users\...` checkout. GitHub Actions run 32550623409 passed 428 focused and 656 full pytest plus every strict foundation stage. |
| Real offline API path smoke gate | ChatGPT | FULL FOUNDATION CI PASS | New zero-network process gate exercises the shipped FastAPI app through health + CSP, raw-credential canary redaction, anonymous project capability, zero-call QUICK chat, MARATHON job capability, durable result retrieval and fail-closed final quality downgrade. GitHub Actions run 32548467255 passed all 40 smoke checks inside the strict foundation gate. |
| Marathon multilingual specialist research | ChatGPT | PUSHED IN PR #7 / FULL FOUNDATION CI PASS | Isolated modules + bounded planner/discovery/API/UI/synthesis hooks are implemented on `chatgpt-marathon-multilingual`. GitHub Actions run 32547266529 passed: 420 focused pytest, 648 full pytest, 593/593 core, cross-domain 633/633, superconductivity 146/146, and architecture/provider/source-boundary/compile gates. CI also exposed and ChatGPT fixed the invalid job-level `runner.temp` context plus the stale 30-minute-only browser assertion. Live zero-cost verification remains a separate honest release gate. |
| MARATHON research-process assurance | ChatGPT | CODE COMPLETE / VERIFY | Existing Claude/ChatGPT lens, concept-ledger, evidence-axis, claim A-E and discovery layers are preserved. MARATHON now always runs five bounded rounds, raises only the privileged preset to 40 ranked/16 full-text sources, records marginal round yield, and exposes a fail-closed 90% process target that is explicitly not truth/profit/success probability. Arbitrary CUSTOM rails remain unchanged. |
| Research relevance hardening | Claude | DONE / INDEPENDENT VERIFY GATE ADDED | Claude domain-aware relevance is in branch; ChatGPT regression tests cover original off-domain failure |
| Source routing + query expansion | Claude | DONE / VERIFY | Domain-aware routing + deterministic fallback present; integrated suite still must run |
| Full-text + large PDF handling | Claude + ChatGPT audit | DONE / VERIFY | Claude removed 4MB blind skip; ChatGPT added honest access wording and whole-document sparse sampling so huge PDFs are not first-N biased |
| Evidence Verification A-E | Claude + ChatGPT integration audit | DONE / VERIFY | Latest Claude strict claim-verification code is merged into integration branch; ChatGPT system-boundary A-E/fail-closed tests remain in release gate |
| Consensus/contradiction correctness | Claude | DONE / VERIFY | Consensus gate present; integrated regression/live benchmark still required |
| Gemini multi-key quota backup | Claude + ChatGPT audit | INTEGRATED / VERIFY | Claude key-pool/local fallback files integrated; ChatGPT closed backup-key ₹0 confirmation bypass and backup-only router/status mismatch |
| Model quota/fallback honesty | Claude + ChatGPT | DONE / VERIFY | Same-model retry vs model/provider/key switch accounting is separated; strict failure/error taxonomy is integrated |
| Multi-provider ₹0 reasoning fallback | ChatGPT | DONE / VERIFY | confirmed Gemini (primary/backup keys) -> confirmed Groq free -> OpenRouter free-only -> localhost Ollama; hard failures are skipped for remainder of run |
| Deterministic no-model evidence fallback | Claude + ChatGPT integration | DONE / VERIFY | If every model provider is unavailable, retrieved evidence/local deterministic reasoning can still produce a conservative result instead of blank output |
| QUICK chat quota resilience | ChatGPT | DONE / VERIFY | Removed direct Gemini-only chat path; trivial small-talk uses 0 API calls; model failure automatically falls back to QUICK evidence research |
| Legacy RAG provider bypass | ChatGPT | FIXED / VERIFY | `rag/pipeline.py` no longer imports/calls Gemini directly; it uses resilient router + conservative document extract fallback |
| Provider-bypass release audit | ChatGPT | DONE / VERIFY | Static audit fails release if production code outside approved adapters directly calls Gemini/Groq/OpenRouter/Ollama generation surfaces |
| Raw provider-error redaction | ChatGPT | HARDENED / VERIFY | Integrated reasoning returns normalized model/provider failure kinds; raw SDK/HTTP/protobuf bodies are excluded from public errors/technical details |
| Discovery/full-text network boundary | ChatGPT | HARDENED / OFFLINE VERIFIED | Shared URL guard blocks private/local/reserved targets, credentials, unsafe ports and redirect pivots; connector/fetch responses enforce content-type and compressed/decompressed byte bounds |
| Human-first presentation contract | ChatGPT audit | DONE / VERIFY | Deterministic presentation guard + A-L tests; sources/audit last; raw technical junk kept out of main explanation |
| Release-state honesty | ChatGPT | DONE / VERIFY | API cannot become `Production Ready` through an env flag; release stays `foundation_verification_pending` until reviewed proof exists |
| Public operational metadata privacy | ChatGPT | HARDENED / VERIFY | project/history/global-job-list routes are fail-closed behind backend-only admin token; public storage health no longer exposes absolute filesystem paths/raw OS errors |
| Static architecture wiring audit | ChatGPT | DONE / VERIFY | Release gate checks end-to-end production wiring, ₹0 chain, storage/security invariants and premature release claims |
| Superconductivity benchmark V2 | Claude + ChatGPT | OFFLINE 146/146 / LIVE RETEST PENDING | Strict offline gate is green; live zero-cost rerun is still a separate required gate |
| Central D-drive runtime routing | ChatGPT | DONE / VERIFY | Heavy runtime/cache/vector/temp/research data routes under configured root; explicit root failure is fail-closed |
| Streaming upload safety | ChatGPT | DONE / VERIFY | Bounded streaming, early stop, partial cleanup, storage reservation |
| ₹0 startup guard | ChatGPT | HARDENED / VERIFY | Paid-key paths blocked; every Gemini primary/backup/list credential is subject to one explicit zero-cost confirmation; Groq confirmed-only; OpenRouter free-only; remote Ollama blocked |
| Request abuse/rate guard | ChatGPT | DONE / VERIFY | Expensive POST endpoints protected without trusting spoofable proxy headers by default |
| Strict browser CORS | ChatGPT | DONE / VERIFY | Wildcard rejected; exact origins only |
| Cloud archive manifest + retry | ChatGPT | DONE / VERIFY | pending -> uploaded_unverified -> verified, durable retry/backoff, local retention |
| Provider-neutral cloud storage | ChatGPT | DONE foundation | Official provider adapters can plug in without core research rewrite |
| Google Drive temporary archive | ChatGPT | PROVIDER SETUP PENDING | Optional official rclone/OAuth route; not a research-engine dependency |
| Async Deep/Maximum research jobs | ChatGPT | DONE / VERIFY | Bounded concurrency, immediate job id, durable lifecycle |
| Job result compaction / size cap | ChatGPT | DONE / VERIFY | Separate gzip result files, configurable per-result cap, deterministic compaction |
| Multi-process job safety | ChatGPT | DONE / VERIFY | Single-writer OS process lock fails closed instead of risking JSON corruption |
| Storage quota / cleanup safety | ChatGPT | DONE / VERIFY | Bounded local workspace; only cloud-verified copies eligible for cleanup |
| Runtime data Git hygiene | ChatGPT | DONE / VERIFY | Tracked `knowledge_graph.json`, `knowledge_store.json`, `error_log.txt` and generated `research_memory/*.json` removed from integration branch; ignored for future runs |
| TeraBox official adapter | ChatGPT | OPTIONAL / BLOCKED | Wait only for official credentials + confirmed zero-cost terms; app development does not wait |
| Encryption for cloud archive | ChatGPT | BLOCKED ON SAFE KEY/RECOVERY DESIGN | No homemade/insecure crypto and no unrecoverable-key design |
| Secondary compact metadata backup | ChatGPT | PLANNED | Only after a genuinely free private destination is selected |
| Patents connector | Claude + ChatGPT integration | DONE / OFFLINE VERIFIED | Official ₹0 EPO Linked Data plus optional official USPTO ODP key; family dedup, relevance traps, legal-status honesty and patent-vs-science separation are release-gated |
| Integrated regression | ChatGPT | FULL FOUNDATION CI PASS / LIVE RETEST PENDING | 2026-08-22 strict gate on PR #9: 428 focused pytest, 656 full pytest, 40/40 real offline API smoke, 593 core checks, provider/architecture audits, cross-domain 633/633 and superconductivity 146/146 |
| Final architecture/integration audit | ChatGPT | FULL FOUNDATION CI PASS / LIVE GATE PENDING | GitHub Actions run 32550623409 passed the complete offline gate; offline evidence is not a 100/100 production sign-off and live zero-cost validation remains open |
| Advanced Scientific Discovery Engine | ChatGPT | CODE COMPLETE / OFFLINE VERIFIED | Structured discovery field includes all 16 planned layers; arbitrary code, automatic real experiments, global-novelty claims and success-probability claims are fail-closed |
| Live ₹0 release runner | ChatGPT | CODE COMPLETE / CREDENTIALS PENDING | No-call preflight is default; real run requires `--execute`, explicit D-root and a currently usable confirmed/free model layer; receipt contains no answer/source text/credentials |
| Exact-revision release proof | ChatGPT | DONE / VERIFY | Foundation/live/deployed receipts now carry validated full Git revisions; dirty checkouts and mixed-commit proof bundles fail closed, and deployed smoke compares Railway's reported build SHA with the expected checkout |

## Latest independent offline validation — 2026-08-22

- Strict default `scripts/run_foundation_gate.py` execution in GitHub Actions run **32550623409**: **PASS across every enforced stage**.
- Focused release pytest: **428 passed**.
- Full `pytest -q tests`: **656 passed**; the strict gate also executed the separate 593-check core regression harness.
- Real FastAPI/session/chat/job/result process smoke: **40 passed, 0 failed**.
- Ordered core regression: **593 passed, 0 failed**.
- Cross-domain adversarial benchmark: **633 passed, 0 failed** across eight domains.
- Superconductivity Benchmark V2: **146 passed, 0 failed**.
- Provider-bypass audit, architecture audit and source-boundary audit: **PASS**.
- This is offline/₹0 verification only. The live zero-cost benchmark and deployment/runtime checks remain required before production sign-off.

## MARATHON research-process assurance — 2026-08-24

- Existing source-derived thinkers/works, concept ledger, multilingual/classic
  text routing, evidence axes, A-E claim checks, falsification and advanced
  discovery were audited and retained instead of duplicated.
- MARATHON no longer stops when an early round merely looks sufficient; all 5
  bounded rounds run so later corpus-derived authors, works, counter-evidence
  and cross-domain leads get searched.
- Fixed preset rails are 40 ranked sources, 16 legal full-text attempts, 6 per
  connector and 360 discovery seconds per round. User-controlled CUSTOM limits
  remain at the older safer 40/4/12 rails.
- `research_assurance` measures rounds, mandatory axis-search, independent
  sources, legal full text, counter-search, reasoning passes, critical-claim A-E
  verification and hypothesis testability. Mandatory gaps fail the target even
  at a numeric 90.
- The percentage is process-checklist coverage only. It is never truth,
  profitability, global exhaustiveness or real-world hypothesis success.

## Marathon multilingual specialist batch — 2026-08-22

- Added a bounded `MARATHON` background mode: 4 reasoning calls, 32 ranked sources,
  4 rounds, 12 legally accessible full-text attempts and 300s discovery budget per round.
- Added exact specialist profiles for mind/cognition, Jung/depth psychology,
  metaphysics, esoteric/occult/Hermetic history, declassified records,
  Freemasonry/secret societies, conspiracy claims and measured-vs-symbolic frequency.
- Fixed raw-substring classification: `physics` no longer fires inside
  `metaphysics`, `science` no longer turns `occult sciences` into ordinary
  science, and scientific domain routing now comes explicitly from the strict
  domain detector instead of accidental `ai` substring matches.
- Added separate official-document, empirical, historical, traditional,
  interpretation, allegation, app-original-hypothesis and unknown lanes.
- Added bounded CIA Reading Room/NARA/FBI Vault/GovInfo site queries for relevant
  questions. Official-document provenance is explicitly not treated as truth proof.
- Added original-preserving Hindi/Hinglish multilingual search planning and an
  honest `translation_required` state for unresolved languages; no paywall,
  copyright or access-control bypass.
- Added a visible evidence-lane section before the existing system-owned
  app-hypothesis section (now titled `APP ORIGINAL RESEARCH LAB`, earlier
  `Humari Hypotheses`) plus structured `specialist_research` API data.
- Local dependency-light checks: **15/15 specialist**, **593/593 core**,
  **633/633 cross-domain**, **146/146 superconductivity**; architecture,
  provider-bypass, source-boundary, compile and web-JS syntax checks pass.
- The current scratch Python lacks `pytest`/FastAPI runtime dependencies, so the
  complete collected pytest suite is not being falsely reported as run; CI or a
  dependency-equipped runtime remains the mandatory final collected-test gate.

## Current independent audit findings fixed

1. Claude's huge-PDF solution was bounded-memory but could bias scanning toward the first N pages. Added deterministic opening + interior + ending sparse sampling and honest partial-reading metadata.
2. QUICK chat directly called Gemini, so Gemini quota could kill normal chat even when fallback logic existed. QUICK now uses the shared zero-cost resilient router, then QUICK evidence research.
3. Legacy `rag/pipeline.py` directly called Gemini and bypassed the router. It now routes through the resilient facade and has a document-only last resort.
4. `/chat/diag` spent a real Gemini generation just to diagnose Gemini. It is now zero-generation by default; optional discovery is confirmation-gated and still does no generation.
5. API release readiness could be promoted through an environment variable. Release state is now hard fail-closed in reviewed code until proof exists.
6. Generated runtime/test state was tracked despite `.gitignore`. Removed and protected by regression.
7. Public `/api`/`/health` exposed absolute runtime filesystem paths and raw OS errors. Public storage status now exposes aggregate capacity/readiness only.
8. Server-side history, project metadata/deletion and global research-job listing were publicly enumerable. These operator surfaces now require a strong backend-only admin token and fail closed as 404 when disabled.
9. The release gate's old “all tests” loop ran pytest files as plain Python, meaning many assertions never executed. A real full `pytest -q tests` stage is now mandatory; direct script mode is used only for explicit `__main__` harnesses.
10. Claude's new Gemini backup-key pool initially created a zero-cost policy gap: backup/list keys could exist while the startup guard checked only `GEMINI_API_KEY`. The guard now covers every supported backup/list variable.
11. Backup-only Gemini config was recognized by the key pool but not by provider-router/status readiness. All three now share the same credential definition and confirmation rule.
12. Provider/Gemini “technical details” could still carry raw HTTP/protobuf/provider payload into a user-visible audit footer. Integrated production reasoning now emits normalized failure kinds only.
13. Discovery connectors and full-text fetches trusted redirects/hosts too broadly and did not share one decompressed-size/content-type boundary. Added one network-safety layer with DNS/IP validation, per-hop redirect checks, exact discovery allowlists, byte caps and sanitized failures.
14. `[UNVERIFIED]` collapsed into speculative claim semantics and source-count grading could still print a top evidence label after a failed claim-level A-E check. Added a distinct internal state with backward-compatible serialization and made final grading consume label/A-E reports.
15. The cross-domain benchmark fake model still parsed the pre-hardening evidence prompt, hiding label/contradiction coverage after the source-data guard changed. Updated the benchmark parser to consume both legacy and hardened prompt grammars and kept the 633/633 gate mandatory.
16. Presentation cleanup treated clickable `[S#]` citations as raw diagnostic URLs and generated a developer-only block on healthy runs. Citation targets now collapse to stable source IDs in the human section while full URLs remain in Sources.
17. Direct script-harness stages lost repository imports when the caller supplied a dependency-only `PYTHONPATH`. The strict runner now prepends the repository root and the default 31-stage gate executes every intended harness successfully.
18. The advanced-discovery roadmap existed only as an aspirational checklist. Added one deterministic, network-free production layer covering all 16 planned stages and wired its bounded result into every research response without extra model calls.
19. Final live verification had no safe one-command boundary. Added a no-call-by-default runner that refuses unconfirmed/non-free model configuration, requires an explicit runtime root and writes only a non-secret summary receipt after an explicitly requested live run.
20. QUICK chat ran its evidence fallback synchronously for up to the 45-second discovery budget, so a proxy/browser timeout could repeatedly replace ongoing work with one generic server-error sentence. Model failure now promotes to the capability-protected durable QUICK job path, while transport/session failures show bounded actionable reasons and preserve the question for retry.
21. Release sign-off required three receipts from one exact commit, but none of the receipt formats enforced that identity. Foundation/live receipts now bind to a clean full SHA, deployment health reports only a validated host-provided build SHA, deployed smoke compares it exactly, and the bounded release-bundle verifier rejects mixed revisions without copying secrets/capabilities.
22. MARATHON could stop early after a superficially sufficient evidence pack and exposed no single audit of how much of the intended process actually ran. It now completes every bounded round, records marginal yield, and reports a mandatory-gap-aware 90% research-process target without turning that number into truth, profitability or hypothesis success probability.

## Required gates before foundation can be called reliable

1. Off-domain source rejection across multiple domains, including false-positive/false-negative cases.
2. Full-text/abstract/snippet/metadata labels accurate; partial huge-PDF coverage honestly distinguished.
3. No false `ESTABLISHED` and no citation-ID-only verification.
4. Claim-level A-E gate enforced: citation + relevance + support + depth + quality.
5. No false consensus; opposition search and reasoning completeness requirements respected.
6. Gemini/free-provider quota failure automatically tries only permitted/confirmed backups; a failed provider does not kill the whole app.
7. Every Gemini backup/list credential obeys the same zero-cost confirmation rule; no backup-only bypass.
8. If every model provider is unavailable, deterministic retrieved-evidence fallback returns a conservative non-blank result where evidence exists.
9. Raw provider/protobuf/HTTP traces never leak into main explanation, chat response or public technical audit.
10. No production API/RAG/chat route may bypass the resilient provider router; provider-bypass audit must pass.
11. Huge PDF processing is bounded-memory AND whole-document sampled when not every page can be inspected.
12. Upload cap stops reading early and cleans partial files.
13. Explicit D-root unavailable/unwritable => fail closed; no silent C: spill.
14. Public health/status does not expose absolute local paths, raw OS errors or secrets.
15. Cloud upload failure/mismatch => local copy preserved; deletion only after verified remote state.
16. Durable job status/result lifecycle, compaction and interrupted restart state all pass.
17. Process lock prevents multiple backend workers from corrupting durable job JSON.
18. Request guard blocks abuse; proxy headers are trusted only when explicitly configured.
19. Server-side history/project/global-job enumeration is not public without backend admin authorization.
20. Generated runtime/error/research-memory state stays out of Git source tree.
21. Full offline regression suite actually executes green on the integrated branch, including full pytest collection.
22. Offline architecture audit and Superconductivity Benchmark V2 execute green after integration.
23. Live zero-cost benchmark reruns after integration and passes relevance/full-text/hypothesis/error-honesty expectations.
24. Final end-to-end path matches the blueprint: discover -> fetch -> process -> evidence -> reason -> criticize -> hypothesize -> verify -> synthesize -> cite/audit.

## Advanced Scientific Discovery Engine — CODE COMPLETE / LIVE VALIDATION PENDING

The deterministic production layer is wired into every research result under
the backward-compatible top-level `discovery` field. It consumes the already
retrieved evidence, hypotheses and verification report; it makes no additional
provider/network call and never upgrades an idea to a proven fact.

- [x] Problem Decomposer — planner sub-questions + domain branches
- [x] Evidence Graph — explicit source/support/challenge edges only
- [x] Physical-Limits Engine — existing verification physics/unit boundary reused
- [x] Hypothesis Generator 2.0 — structured six-field/testability contract reused
- [x] Novelty Checker — checked-evidence/project-memory screening; never global novelty
- [x] Hypothesis Tournament — test-priority score, explicitly not truth probability
- [x] Falsification Engine — measurable prediction/test/reject-condition completeness
- [x] Simulation / Code Executor — bounded numeric AST only; no arbitrary Python/import/files/network/subprocess
- [x] Virtual Experiment Designer — design-only; real execution always human-approved
- [x] Recursive Research Loop — maximum two proposed extra iterations; never auto-network
- [x] Confidence Calibration — evidence/access/verification caps; no success probability
- [x] Weakest-Link Analysis — minimum evidence/verification/falsifiability factor
- [x] Alternative-Path Generator — competing-explanation-first plans, no invented claim
- [x] TRL / Reality Ladder — literature-only assessment hard-capped at level 3
- [x] Discovery Memory — compact bounded checkpoint, legacy-memory compatible
- [x] Domain-Specific Validation Layer — per-domain requirements and no real-world auto-approval
## Local deployment actions

| Task | Owner | Status | Files | Commit |
|---|---|---|---|---|
| Feature-branch push | ChatGPT | available through connected GitHub workflow | — | — |
| MARATHON exact-revision live gate | ChatGPT | CODE COMPLETE / OPERATOR KEY REQUIRED | `scripts/run_live_zero_cost_gate.py`, `RUN_LIVE_ZERO_COST_GATE.ps1` | — |
| Railway mein confirmed-free model key + live MAXIMUM test | User/local setup | pending | Railway Variables | — |
| Android `RetrofitClient.kt` ka `BASE_URL` Railway URL par | User/local setup | optional | `InfinityResearchAI/.../RetrofitClient.kt` | — |
| Real full pytest | ChatGPT | PASS — 633/633 on final post-merge tree | — | — |
| USPTO ODP free key (optional) → Railway `USPTO_ODP_API_KEY` | User/local setup | optional | Railway Variables | — |
| Railway timeout knob (optional): `GEMINI_CALL_TIMEOUT` | User/local setup | optional | Railway Variables | — |

The live runner is also code-complete: `RUN_LIVE_ZERO_COST_GATE.bat` performs a
no-call preflight by default and requires `--execute` plus an explicitly
confirmed/free model layer for the real benchmark. Its receipt excludes answer,
prompt, sources/URLs and credentials.

Every generated hypothesis must eventually carry support, counter-evidence, assumptions, unknowns, falsification criteria, required experiment/simulation, expected impact and calibrated confidence. Never invent arbitrary 90–95% real-world success claims.

## UI/product requirements remembered

- Modes: Quick / Deep / Maximum / Marathon / Custom.
- Real progress/stages, not fake percentages.
- Sources: uploaded docs + legally/publicly accessible papers, books, reports, patents, datasets, webpages and video/audio transcripts.
- Easy teacher-like Hinglish first; technical source/audit layer afterward.
- Main answer must not be cluttered by raw logs/DOIs/errors.
- Android stays a thin client; provider secrets stay backend-side.

## Coordination rule

Before starting a task, check this file. Do not edit files another agent currently owns as ACTIVE. After each major batch, commit/push and refresh this status. A reported test count from another agent is evidence of progress, not independent proof; final sign-off requires ChatGPT's independent integrated gate plus live benchmark.

Jo pehle se maujood hai (nayi shuruaat nahi karni padegi): `knowledge_graph_improved.py`
mein `extract_entities_improved`, `extract_relationships_improved`,
`build_knowledge_graph` aur `find_cross_disciplinary_connections` already hain;
`knowledge_graph.py` sirf ek optional adapter hai (`related_note`, `store`,
`stats`) jo missing module par chup-chaap band ho jaata hai. Yaani "enhance" ka
matlab naya module nahi — inhi ke beech ki wiring + cross-field edges ka
scoring hai.

## Naya batch — Cross-Domain Research Reliability Benchmark (Owner: Claude)

intel ka instruction (2026-08-21): *"Ab koi naya flashy feature mat add karo.
Pehle prove karo ki research engine alag-alag fields mein genuinely reliable hai."*
Maqsad saaf tha — superconductivity par jo tuning hui, wo overfitting hai ya nahi.

Aath bilkul alag domain, har ek mein 12 jaan-boojh kar bichhaye gaye trap
(kaam ka source, keyword-overlap wala dhoka, duplicate/mirror, snippet-only,
abstract-only, asli full text, ghatiya quality, ulta evidence, sirf-support
evidence, na-kaafi evidence, retracted metadata, model-dead) aur har domain par
16 category ke automatic check.

| Task | Owner | Status | Files | Commit |
|---|---|---|---|---|
| 8-domain benchmark harness + fixtures + scorecard + confusion matrix | Claude | done | `tests/benchmark_cross_domain.py` (naya) | (is batch mein) |
| 8 domain profiles (medicine/materials/energy/engineering/cs_ai/archaeology/economics/biology) + `must` branches | Claude | done | `research_engine/domain.py` | (is batch mein) |
| stance lexicon domain-neutral (contradiction har field mein bane) | Claude | done | `research_engine/contradiction.py` | (is batch mein) |
| label gate ka do-pass hisaab ek jagah (`merge_reports`) | Claude | done | `research_engine/claim_labels.py`, `research_engine/orchestrator.py` | (is batch mein) |
| galat conversion par khadi comparison pakdo | Claude | done | `research_engine/physics_checks.py` | (is batch mein) |
| hypothesis cap evidence gate ki izzat kare | Claude | done | `research_engine/hypothesis.py` | (is batch mein) |
| lone-keyword trap rejection (`Bearing witness` type) | Claude | done | `research_engine/relevance.py` | (is batch mein) |
| pytest bhi wahi test chalaye jo script chalati hai | Claude | done | `tests/test_pdf_chunking.py`, `tests/test_answer_structure.py`, `tests/test_consensus_gate.py`, `tests/test_relevance_domain.py`, `test_research_engine.py` | (is batch mein) |

Chalane ka tareeka: `python3 tests/benchmark_cross_domain.py` (poora offline —
network nahi, API key nahi, paisa nahi). Aakhir mein per-domain scorecard
(domain / relevance / evidence / verification / consensus / hypothesis / fallback
/ presentation) aur domain-confusion matrix chhapti hai.

Benchmark ne 5 asli bug pakde (test aasan karke nahi, code theek karke gaye):

1. **Contradiction sirf medicine mein banti thi.** Stance lexicon poori tarah
   clinical-trial ki angrezi thi ("efficacious", "reduces risk"), isliye
   engineering / cs_ai / archaeology / economics ke sources NEUTRAL nikalte the
   aur "iske against kya mila?" khaali reh jaata tha. Ab null-result ki
   domain-neutral bhaasha bhi cue hai, aur `_all_negated()` ki wajah se
   "no improvement" support mein nahi ginta.
2. **Jis field ka sabse bada failure mode retracted claim hai, usi ka
   "kya ye replicate hua?" search nahi hota tha.** Superconductivity ke 17
   branches mein `expanded_queries(limit=9)` replication/retraction wala angle
   kaat deta tha. Ab `Branch.must` hai aur `controversy` + `mechanism` kabhi
   nahi kat‑te.
3. **Audit apna hi kaam kam karke batata tha.** Strict pass line ko pehle hi
   `[UNVERIFIED]` kar deta tha, isliye depth pass imaandaari se `checked: 0`
   likhta tha — jawab mein downgrade dikhta tha par `label_report` khaali.
   `merge_reports()` dono pass ka total deta hai.
4. **Galat conversion par khadi tulna pass ho jaati thi** ("730 days (20 years),
   jo 5 years se zyada hai" — 730 din ≈ 2 saal). Ab restatement asli value se
   dobara jaanchi jaati hai.
5. **Evidence gate kaagaz par reh jaata tha.** Gate 1 hypothesis allow karta,
   par parser ka floor `max(3, ...)` tha — report mein teen chhap jaati thi.

## Naya batch — ₹0 Patent Research + Patent Evidence Integration (Owner: Claude)

intel ka instruction (2026-08-21): *"Advanced Scientific Discovery Engine abhi
start MAT karo. Pehle original source-discovery blueprint ka real missing piece
close karo: PATENTS."* Hard rule: koi paid API nahi, koi scraping/bypass nahi,
sirf official/public endpoints, credentials repo mein kabhi nahi, aur provider
down ho to engine crash na kare.

| Task | Owner | Status | Files | Commit |
|---|---|---|---|---|
| PATENT first-class source type (`PatentMeta`, read-depth, family key, status label, novelty helpers) | Claude | done | `research_engine/patents.py` (naya) | (is batch mein) |
| Do keyless/official connector + `safe_search()` failure contract | Claude | done | `research_engine/connectors/patent_connector.py` (naya), `research_engine/connectors/__init__.py` | (is batch mein) |
| `SourceType.PATENT`, patent-aware `SourceRecord` / `EvidencePack` counters | Claude | done | `research_engine/models.py` | (is batch mein) |
| Routing: patent connector sirf invention/prior-art/novelty sawaal par | Claude | done | `research_engine/planner.py`, `research_engine/depth.py`, `research_engine/source_discovery.py` | (is batch mein) |
| Patent-family collapse (US/EP/WO = ek evidence) | Claude | done | `research_engine/dedup.py` | (is batch mein) |
| "Patent ≠ proof" ke teen alag gate | Claude | done | `research_engine/claim_labels.py`, `research_engine/claim_verification.py`, `research_engine/consensus_gate.py` | (is batch mein) |
| Prompt-level patent rule (sirf patent pack par inject) | Claude | done | `research_engine/gemini_reasoning.py` | (is batch mein) |
| Prior-art honesty + novelty-overclaim catcher report mein | Claude | done | `research_engine/orchestrator.py` | (is batch mein) |
| Relevance guard patent metrics + "filtered ≠ 0 mila" | Claude | done | `research_engine/relevance.py` | (is batch mein) |
| 152-check offline patent suite (10 deliberate trap) | Claude | done | `tests/test_patents.py` (naya) | (is batch mein) |

Provider chunav (dono ₹0 aur official):

- **EPO Linked Open Data SPARQL** (`epo_lod`) — `https://data.epo.org/linked-data/query`,
  bilkul **keyless**, EPO ka apna public endpoint. Fair-use ~10 search/min hai
  isliye `retries=0` aur `LIMIT 5`. SPARQL injection band: har quoted term
  `^[0-9a-z \-]*$` par saaf hota hai, FILTER sirf REQUIRED triple par lagti hai.
  EPO ka legal-status data official publication **nahi** maana jaata — isliye
  source string mein wahi likha jaata hai.
- **USPTO Open Data Portal** (`uspto_odp`) — free account ki API key se, isliye
  **optional**: key na ho to connector `available_names()` mein hi nahi aata aur
  reason `no_key` jaata hai (crash nahi). Key sirf `USPTO_ODP_API_KEY` env se
  padhi jaati hai, sirf `X-API-KEY` header mein jaati hai, aur kisi log/record/
  URL/params mein leak nahi hoti (test isse assert karta hai).

Patent evidence science evidence se **alag** rehta hai, teen jagah:

1. `claim_labels.line_verdict` — patent-only line `full_text` par bhi
   `[SOURCE-REPORTED]` rehti hai (reason: "LEGAL dawe").
2. `claim_verification.check_d` — patent-only claim ka verdict `UNKNOWN`.
3. `consensus_gate` ka 7th condition `science_beyond_patents` — sirf tab judta
   hai jab pack mein patent hain, aur 3 non-patent science source maangta hai.
   Plus `coverage_report()["prior_art"]` ek alag block hai, science counters
   mein mila hua nahi.

Chalane ka tareeka: `python3 tests/test_patents.py` (poora offline — network
nahi, API key nahi, paisa nahi). 11 stage, **152 check**. Suite khokhli nahi
hai: teen mutation inject karke check kiya gaya — family-collapse band karne par
7 FAIL, `patent_intent` hamesha-on karne par 1 FAIL, `is_patent` hamesha False
karne par 30 FAIL.

Regression (sab is sandbox mein 2026-08-21 ko chalaye gaye, sab `rc=0`):
`tests/benchmark_cross_domain.py` **633/633**, `tests/benchmark_superconductivity.py`
**146/146**, `test_research_engine.py` **593 pass / 0 fail**,
`test_missing_features.py` 14 assertion, aur `tests/test_*.py` ki saari 19 file
`rc=0` (test_claim_verification 143/0, test_hypothesis_quality 137/0,
test_quota_backup 122/0, test_physics_sanity 86/0, test_audit_accounting 70/0,
test_pdf_chunking 56/0, test_answer_structure 51/0, test_search_rounds 51/0,
test_relevance_domain 39/0, test_consensus_gate 28/0, test_patents 152/0 —
baaki file summary line print nahi karti). Asli `pytest` is sandbox mein import
hi nahi hoti (neeche wala gap), isliye pytest ka naya total intel ke Windows se
aayega — `tests/test_patents.py` module level par sirf ek test deti hai
(`test_patents_all_checks_pass`), isliye pichhle **194** se **195** hona
chahiye.

## Live bug fix — "Abhi server se baat nahi ho paayi" (Owner: Claude, 2026-08-21)

intel ki report: website par sawaal bhejo, aur aakhir mein
"Abhi server se baat nahi ho paayi. Thodi der baad phir bhejo — main yahin hoon 🙂"
aa jaata tha. Hukum: **"kuch htana mt, bss isko fix kro"** — isliye ek bhi
feature, model, key-rotation, ya wo pyaari line khud, kuch bhi hataya NAHI gaya.
Sirf jodha gaya hai.

Asli wajah do thi (dono ab band):

1. **Server par ek bhi call par timeout nahi tha.** `generate_content()` seedha
   call hota tha; Google ka SDK default mein anaadi kaal tak ruk sakta hai. Ek
   latki hui call poori HTTP request ko rok kar rakhti thi, aur beech mein
   browser/Railway gateway connection kaat deta tha. User ko "server down" lagta
   tha, jabki server sirf ek call par atka hua tha.
2. **Browser har gadbad ko EK hi line bana deta tha.** Har fetch
   `await (await fetch(...)).json()` tha — koi `r.ok` check nahi, koi status
   nahi. 502 / khaali body / HTML error page / timeout, sab exception ban kar
   wahi ek line dikhate the. Aur DEEP/MAX ka jawab, jo server par ban CHUKA
   hota tha, connection katne par hamesha ke liye kho jaata tha.

Kya badla:

| File | Kya hua |
|---|---|
| `research_engine/gemini_model.py` | naya `call_timeout()` (env `GEMINI_CALL_TIMEOUT`, 10..600s, default 75) + `generate(model, prompt, timeout=None)`. `request_options` support per-callable `inspect.signature` se pata karta hai, isliye purane SDK aur test ke nakli model bina timeout waise hi chalte hain. |
| `research_engine/chat.py` | QUICK chat ki do haddein: `CALL_TIMEOUT_SECONDS` (`GEMINI_CHAT_TIMEOUT`, def 45) aur `TOTAL_BUDGET_SECONDS` (`GEMINI_CHAT_BUDGET`, def 100). `_one_key_try` mein monotonic deadline — budget khatam hote hi rukta hai, par khaali haath nahi: offline parat phir bhi jawab deti hai. `key_dead`, 4-model cap, key rotation, offline fallback — sab jaise the waise hain. |
| `research_engine/gemini_reasoning.py` | deep-research ki call bhi ab `gemini_model.generate()` se jaati hai. Timeout `model_errors.classify` ke liye TRANSIENT hai, isliye purana retry/backoff hi chalta hai — model band nahi hota. |
| `web/index.html` | naya non-throwing network layer (`readBody`/`postJSON`/`getJSON`), `reasonLine(res)` jo status ko insaani "Wajah: …" banata hai, QUICK par ek automatic retry, "Phir bhejo" button (sawaal dobara type nahi karna padta), aur DEEP/MAX ke liye `matchingAnswers()` + `recoverAnswer()` jo `GET /api/v1/history/{project_id}` se kho gaya jawab wapas le aata hai (baseline ginti se, taaki purana jawab na uthe; sirf GET, nayi research trigger nahi hoti). |

Naya test: `python3 tests/test_chat_resilience.py` — 10 stage, **49 check**, poora
offline (na network, na API key). Mutation proof: `generate()` se timeout hataane
par 4 FAIL, purani style wali `index.html` dene par 12 FAIL.

Commit: **a14bc94** (pehla hissa) + follow-up (neeche wala flicker fix).

**Follow-up (usi din, intel ki doosri report):** recovery chal rahi thi par status
line "aati thi phir hat jaati thi". Wajah bug nahi, **do likhne wale** the —
`done = true` recovery ke BAAD set hota tha, isliye purana `poll()` (1.2s) aur
recovery ka `onStatus` (3s) dono usi `.stg` element par likhte rehte the: ek
"(connection toota tha…)" likhta, doosra usse mita deta. Ab `done = true` POST ke
turant baad hai, `poll()` apni aakhri likhai bhi `if(done) return;` se rokta hai,
aur status+log dono ek hi `renderLog()` se bante hain (recovery ke waqt log ab
khaali nahi hota — server ka asli kaam dikhta rehta hai). Saath hi recovery ka
intezaar MAX mode ke hisaab se lamba kiya gaya: hard deadline 12 → **30 minute**,
plus ek **stall guard** (6 minute tak progress bilkul na hile to chhod dete hain)
— yaani lamba MAX run beech mein chhoda nahi jaata, par jam jaane par bekaar
intezaar bhi nahi hota.

Regression (sab is sandbox mein 2026-08-21 ko, sab `rc=0`):
`tests/benchmark_cross_domain.py` **633/633**,
`tests/benchmark_superconductivity.py` **146/146**,
`test_research_engine.py` **593/0**, `test_missing_features.py` 14 assertion,
aur `tests/test_*.py` ki saari **20** file `rc=0` (nayi wali samet).
pytest ka total `194 → 196` hona chahiye (patent batch se +1, is fix se +1) —
asli ginti intel ke Windows se aayegi.

## Naya batch — RV-AI Advanced Research Upgrade §4–§25 (Owner: Claude, 2026-08-22)

Ye batch live **dark-matter run ki 17 galtiyon** se shuru hua tha (18 retrieved vs 9
cited, average relevance ≈0.43, irrelevant calibration/exoplanet papers, CMB/BBN/
Bullet-Cluster/lensing/LSS/dwarf axes gayab, 14 × `[NO-SOURCE]`, counter-search
nahi, S9/S11/S12 mislabelled, sirf-saal wale nakli contradictions, PBH/dark-photon
ko "naya" batana, adhoora jawab `COMPLETE` + `✅ VERIFIED`, raw 429/504 jawab mein,
duplicate footer, gayab hoti progress line).

| Kaam | Owner | Status | Files |
|---|---|---|---|
| §4 quality contract + §7/§19 counters aur `quality_context` producer | Claude | done | `research_engine/quality_producers.py` (naya) |
| §5 query axes + per-axis coverage + retry ladder | Claude | done | `research_engine/evidence_axes.py` (naya), `planner.py`, `query_builder.py` |
| §6 relevance proposition-test + structured reject codes | Claude | done | `research_engine/relevance.py` |
| §8/§9 claim evidence spans + paanch access-depth label | Claude | done | `research_engine/claim_verification.py`, `claim_labels.py`, `models.py` |
| §10/§11 counter-search consensus se pehle + structured contradictions | Claude | done | `research_engine/contradiction.py`, `orchestrator.py` |
| §13–§16/§18 hypothesis/novelty/prediction/experiment/confidence contract | Claude | done | `research_engine/hypothesis.py` |
| §17 calculation records + 4 alag verdict | Claude | done | `research_engine/physics_checks.py` |
| §12/§20 answer order + `APP ORIGINAL RESEARCH LAB` alag + 4 alag state | Claude | done | `research_engine/answer_order.py` (naya), `research_state.py` (naya), `synthesizer*.py` |
| §21/§22 UI tabs + progress snapshot + recovery contract | Claude | done | `web/index.html`, `tests/test_recovery_ui_contract.py` |
| §23 saat nayi Claude-owned test file (20 behaviour) | Claude | done | `tests/test_{quality_context_producers,relevance_axis_coverage,structured_contradictions,calculation_records,novelty_contract,original_research_lab,research_output_separation}.py` |
| §24 dark-matter acceptance matrix DM-01…DM-17 | Claude | done | `tests/benchmark_dark_matter_acceptance.py` (naya) |

**§24 ka nateeja: 285 check pass, 0 fail — 17/17 live galtiyon ka darwaaza band
(`CLOSED`).** Har row ek hi live galti par khadi hai, aur uski apni pass/fail ginti
hai, taaki scorecard padh kar pata chale "kaunsa jhooth ab bhi mumkin hai". Chhe
variant par chalti hai (`live, dead, bad_math, overclaim, support, thin`) aur
`tests/benchmark_cross_domain.py` ka harness bina badle reuse karti hai.

**§24 ne do asli bug pakde (dono theek kiye gaye):**

- `quality_producers.context_block()` pipeline mein **kabhi call hi nahi hota tha**,
  isliye §19 ka tri-state vaakya sirf tests tak pahunchta tha — user ke audit mein
  "0" chhap sakta tha us check ke liye jo chala hi nahi tha. Ab
  `render_unknown_block()` + `inject_unknown_block()` audit section mein naam le kar
  likhte hain, aur `orchestrator.py` inhe `rescan_final_answer` ke **baad** aur
  §20 state block se **pehle** inject karta hai.
- `synthesizer.py` ka apna imaandaar vaakya "…strong claims ko full-text verified
  kehna allowed nahi hai" khud access-depth detector mein phans jaata tha (detector
  theek hai — banned label case-insensitive dhoondta hai), jisse `thin` run ke audit
  mein jhoothi "1 overclaim" ginti banti thi. Detector kamzor nahi kiya; humari prose
  badli gayi ("'poora text padh kar check kiya' wala dava").

Regression (sab is sandbox mein 2026-08-22, sab `rc=0`, koi live provider call nahi):
`test_research_engine.py` **594/0**, `tests/run_pytest_style_suites.py` **266/0**
(26 skip = sandbox mein `pytest`/`fastapi` nahi, 5 NOT-A-SUITE demo script),
`tests/benchmark_cross_domain.py` **649/649**,
`tests/benchmark_superconductivity.py` **156/156**,
`tests/benchmark_dark_matter_acceptance.py` **285/0 (17/17 CLOSED)**,
aur PR #14/#15/#16 ki apni suites bhi green — incl.
`tests/test_multiline_claim_grounding.py` 10/10, `test_claim_verification.py` 150/0,
`test_hypothesis_quality.py` 141/0, `test_answer_structure.py` 56/0,
`test_calculation_records.py` 84/0, `test_relevance_axis_coverage.py` 132/0.

**PR #16 ke saath merge:** `044a7d9` ne `verify_answer()` ka loop line-by-line se
`labelled_claim_spans()` ke bounded block par badal diya, aur Claude ka §8 kaam usi
loop mein `section`/`claim_id`/`critical` jodta hai. **Dono rakhe gaye:** block PR #16
ka, aur section ek precomputed `section_at` list se (line index → aakhri `##` heading).
`citation.py` / `evidence_verification_legacy.py` chhue nahi gaye.

## Known gaps (jaan-boojh kar khule)

- **⚠️ ChatGPT-owned file mein §14 ka edit hua (intel ko report kiya gaya).**
  `research_engine/synthesizer.py` ke 4 helper (`_api_accounting_block`,
  `_access_block`, `_quality_line`, `_numbers_check`) aur
  `research_engine/orchestrator.py` ka `_confidence_note` badle gaye — kyunki naye
  imaandaar counters aur denominators report mein chhapte wahin se hain. Sirf ye
  helper badle, koi feature hataya nahi gaya. Merge conflict ho to §14 ka logic
  `gemini_reasoning.api_accounting()` mein poora maujood hai; presentation dobara
  banana aasan hai.
- **Claim-label strict rule ab lagu hai, par `claim_labels.py` chhua NAHI gaya.**
  Final rule ("poora text mila par support nahi mila" → `[UNVERIFIED]`, na ki
  `SOURCE-REPORTED`) `research_engine/claim_verification.py` ke naye
  `enforce_strict_labels()` / `strict_label_line()` mein hai, aur orchestrator
  usse depth-wale downgrade se PEHLE chalata hai. `claim_labels.py` ka default
  behaviour (`check_entailment=False`, sirf reading depth) bilkul waisa hi hai —
  us file mein ek line bhi nahi badli. Regression:
  `tests/test_claim_verification.py::test_strict_label_contract`.
- **`.github/workflows/foundation-tests.yml` (ChatGPT-owned) `pytest -q` chalata
  hai.** Meri taraf ka aadha hissa 2026-08-21 ko theek kar diya gaya: jin 4 suites
  ke check `main()` ke andar the ya jo flat script thi, unme ab module-level
  `def test_...(): assert main() == 0` wrapper hai — `tests/test_pdf_chunking.py`
  (ye pytest mein **collection error** de rahi thi, kyunki module level par
  `sys.exit()` tha), `tests/test_answer_structure.py`,
  `tests/test_consensus_gate.py`, `tests/test_relevance_domain.py`. Script wala
  purana tareeka bilkul waisa hi chalta hai. Aur 2026-08-21 ko hi
  `test_research_engine.py` ke 22 stage function ka naam `test_*` se `_check_*`
  kar diya gaya (sirf naam — andar ka ek bhi check nahi badla) + ek hi
  module-level entry `test_research_engine_all_checks_pass()` jo `main()`
  chalata hai. Wajah intel ke asli pytest run se aayi: `pytest -q tests/
  test_research_engine.py` → **212 passed, 3 errors** — teen stage
  (`_check_contradictions`, `_check_verification`, `_check_synthesizer`) agle
  stage ka `pack` argument lete hain, aur pytest ne usko fixture samajh liya
  ("fixture 'pack' not found"); do stage value return karte the → future
  pytest mein error banne wali `PytestReturnNotNoneWarning`. Ab pytest wahi
  ek run karta hai jo CI (`python test_research_engine.py`) karti hai —
  same kram, same 593 check. **Baaki gap ChatGPT ka hai:** wo
  workflow 20+ aisi test files reference karta hai jo `main` par maujood hi nahi
  (`tests/test_upload_safety.py`, `tests/test_evidence_verification.py`,
  `tests/test_domain_guardrails.py`, `tests/test_presentation_guard.py`,
  `tests/test_user_presentation_contract.py` … `git ls-files tests` mein ek bhi
  nahi hai), aur repo root ki `test_academic.py` / `test_connectors.py` /
  `test_kg.py` / `test_progress.py` / `test_safety.py` / `test_web_search.py` se
  pytest 0 test collect karti hai. Ye file aur wo tests ChatGPT ke naam par hain,
  isliye chhue nahi.
- **Is sandbox mein asli `pytest` chal hi nahi saka.** `pip install pytest`
  blocked hai (proxy 403 — ₹0 se koi lena-dena nahi, network hi band hai).
  Iski jagah ek pytest-jaisa collector chalaya gaya jo har test file se
  module-level `test_*` functions collect karke chalata hai: **collected=219,
  pass=216, fail=0, error=0, skip=3** (3 skip = `test_research_engine.py` ke wo
  helper jo argument lete hain). Asli `pytest 8.3.4` intel ke Windows par chala
  (2026-08-21): pehle 4 nayi wrapper suites → **4 passed**; poori `pytest -q
  tests/ test_research_engine.py` → **212 passed, 3 errors** (wahi 3 fixture
  wale, upar likhe gaye). Un 3 ko theek karne ke baad `test_research_engine.py`
  se pytest 19 ke bajaye 1 test collect karta hai, aur intel ka agla run isi ko
  confirm karta hai: **194 passed, 0 errors, 2 warnings in 7.70s** (dono warning
  `google._upb` protobuf ki DeprecationWarning hain, humare code ki nahi).
  Commit `51a07f7` push ho chuka hai.
- **§8 ke liye ChatGPT-owned `synthesizer.py` JAAN-BOOJH KAR NAHI chhua.**
  `key_switches` / `active_key` ko audit block mein alag row banane ke liye
  `_api_accounting_block()` badalna padta — wo file ChatGPT ki hai, isliye rok
  diya. Info gaayab nahi hai: ye dono cheezein `gemini_reasoning.usage_note()`
  mein jaati hain aur audit block wahi note pehle se chhapta hai
  (`api_accounting()` dict mein `keys_available` / `key_switches` /
  `active_key` / `keys_note` bhi maujood hain, jab ChatGPT chaahe use kar le).
- **~~Patents connector nahi hai~~ — 2026-08-21 ko ho gaya.** CUSTOM mode ka
  `use_patents` switch bhi ab synchronous aur durable-job dono request schemas
  se runtime config tak wired hai. Source presentation mein `claims` ka raw
  label hata kar ab **PATENT CLAIMS REVIEWED** + explicit “legal claim, science
  proof nahi” disclosure aata hai, aur access-depth total mein claims-level
  patents bhi gine jaate hain. Ek limitation abhi honest disclosure mein rehti
  hai:
  - **`family_id` sirf EPO deta hai.** USPTO ODP wale record ka `family_id`
    jaan-boojh kar `""` rehta hai (ODP is endpoint par bharosemand family id
    nahi deta) — us case mein family key priority-date + title slug se banti
    hai, aur kuch bhi na mile to key khaali rehti hai matlab wo record kabhi
    dedup mein nahi girta. Guess karke do alag invention ko ek maan lena isse
    bura hota.
- Kuch declared-but-unused packages `requirements.txt` mein hain. Inhe **hataya
  nahi gaya** (feature/dependency kabhi nahi hatate — intel ka rule).
