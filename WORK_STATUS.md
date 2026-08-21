# Infinity Research AI — Master Work Status

This file is the coordination source of truth for multi-agent work.

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

## Active foundation status

| Task | Owner | Status | Notes |
|---|---|---|---|
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
| Human-first presentation contract | ChatGPT audit | DONE / VERIFY | Deterministic presentation guard + A-L tests; sources/audit last; raw technical junk kept out of main explanation |
| Release-state honesty | ChatGPT | DONE / VERIFY | API cannot become `Production Ready` through an env flag; release stays `foundation_verification_pending` until reviewed proof exists |
| Public operational metadata privacy | ChatGPT | HARDENED / VERIFY | project/history/global-job-list routes are fail-closed behind backend-only admin token; public storage health no longer exposes absolute filesystem paths/raw OS errors |
| Static architecture wiring audit | ChatGPT | DONE / VERIFY | Release gate checks end-to-end production wiring, ₹0 chain, storage/security invariants and premature release claims |
| Superconductivity benchmark V2 | Claude + ChatGPT | PENDING LIVE RETEST | Offline benchmark is in strict gate; live zero-cost rerun still required |
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
| Patents connector | ChatGPT | PENDING OFFICIAL-AUTH DESIGN | No unofficial scraping. Add only through an official zero-cost route |
| Integrated regression | ChatGPT | REQUIRED / NEEDS ACTUAL EXECUTION | Strict runner now executes focused pytest + full `pytest -q tests` (not fake `python test_file.py` imports), core regression, script harnesses, provider/architecture audits and Superconductivity Benchmark V2 |
| Final architecture/integration audit | ChatGPT | ACTIVE | Manual audit continues; every finding is fixed before foundation sign-off |

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

## Advanced Scientific Discovery Engine — after foundation passes

- Problem Decomposer
- Evidence Graph
- Physical-Limits Engine
- Hypothesis Generator 2.0
- Novelty Checker
- Hypothesis Tournament
- Falsification Engine
- Simulation / Code Executor
- Virtual Experiment Designer
- Recursive Research Loop
- Confidence Calibration
- Weakest-Link Analysis
- Alternative-Path Generator
- TRL / Reality Ladder
- Discovery Memory
- Domain-Specific Validation Layer

Every generated hypothesis must eventually carry support, counter-evidence, assumptions, unknowns, falsification criteria, required experiment/simulation, expected impact and calibrated confidence. Never invent arbitrary 90–95% real-world success claims.

## UI/product requirements remembered

- Modes: Quick / Deep / Maximum / Custom.
- Real progress/stages, not fake percentages.
- Sources: uploaded docs + legally/publicly accessible papers, books, reports, patents, datasets, webpages and video/audio transcripts.
- Easy teacher-like Hinglish first; technical source/audit layer afterward.
- Main answer must not be cluttered by raw logs/DOIs/errors.
- Android stays a thin client; provider secrets stay backend-side.

## Coordination rule

Before starting a task, check this file. Do not edit files another agent currently owns as ACTIVE. After each major batch, commit/push and refresh this status. A reported test count from another agent is evidence of progress, not independent proof; final sign-off requires ChatGPT's independent integrated gate plus live benchmark.
