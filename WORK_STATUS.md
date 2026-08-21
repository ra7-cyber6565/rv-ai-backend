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
| Evidence Verification A-E | ChatGPT independent implementation | DONE / VERIFY | Claim-level citation, relevance, available-text support, depth and quality/retraction gate added and connected to verification; regression tests added |
| Consensus/contradiction correctness | Claude | DONE / VERIFY | Consensus gate present; integrated regression/live benchmark still required |
| Model quota/fallback honesty | Claude + ChatGPT ₹0 guard | DONE / VERIFY | Error taxonomy/dynamic model discovery present; Gemini key blocked in zero-cost mode unless owner explicitly confirms no paid spend path |
| Human-first presentation contract | ChatGPT audit | DONE / VERIFY | Deterministic presentation guard + A-L tests; sources/audit last; raw technical junk kept out of main explanation |
| Superconductivity benchmark V2 | Claude + ChatGPT | PENDING LIVE RETEST | Must rerun after integrated offline suite with confirmed zero-cost Gemini setup |
| Central D-drive runtime routing | ChatGPT | DONE / VERIFY | Heavy runtime/cache/vector/temp/research data routes under configured root; explicit root failure is fail-closed |
| Streaming upload safety | ChatGPT | DONE / VERIFY | Bounded streaming, early stop, partial cleanup, storage reservation |
| ₹0 startup guard | ChatGPT | DONE / VERIFY | Known paid API keys blocked; Gemini requires explicit zero-cost confirmation |
| Request abuse/rate guard | ChatGPT | DONE / VERIFY | Expensive POST endpoints protected without trusting spoofable proxy headers by default |
| Strict browser CORS | ChatGPT | DONE / VERIFY | Wildcard rejected; exact origins only |
| Cloud archive manifest + retry | ChatGPT | DONE / VERIFY | pending -> uploaded_unverified -> verified, durable retry/backoff, local retention |
| Provider-neutral cloud storage | ChatGPT | DONE foundation | Official provider adapters can plug in without core research rewrite |
| Google Drive temporary archive | ChatGPT | PROVIDER SETUP PENDING | Optional official rclone/OAuth route; not a research-engine dependency |
| Async Deep/Maximum research jobs | ChatGPT | DONE / VERIFY | Bounded concurrency, immediate job id, durable lifecycle |
| Job result compaction / size cap | ChatGPT | DONE / VERIFY | Separate gzip result files, configurable per-result cap, deterministic compaction |
| Multi-process job safety | ChatGPT | DONE / VERIFY | Single-writer OS process lock fails closed instead of risking JSON corruption |
| Storage quota / cleanup safety | ChatGPT | DONE / VERIFY | Bounded local workspace; only cloud-verified copies eligible for cleanup |
| TeraBox official adapter | ChatGPT | OPTIONAL / BLOCKED | Wait only for official credentials + confirmed zero-cost terms; app development does not wait |
| Encryption for cloud archive | ChatGPT | BLOCKED ON SAFE KEY/RECOVERY DESIGN | No homemade/insecure crypto and no unrecoverable-key design |
| Secondary compact metadata backup | ChatGPT | PLANNED | Only after a genuinely free private destination is selected |
| Integrated regression | ChatGPT | REQUIRED / BLOCKED ON ACTUAL RUN | CI workflow contains foundation gates, but connected GitHub API currently reports no workflow run/status for PR head; do not claim green |
| Final architecture/integration audit | ChatGPT | REQUIRED | Cross-module blueprint audit after offline tests; fix all failures before foundation sign-off |

## Current independent audit finding being fixed

Claude's huge-PDF solution was bounded-memory, but for documents larger than the page scan budget it could inspect only the first N pages. That systematically risks missing late methods/results chapters. ChatGPT added deterministic whole-document sparse sampling: opening pages + ending pages + evenly spread interior pages, then relevance selection. Audit metadata explicitly reports sparse coverage and never claims the whole document was read.

## Required gates before foundation can be called reliable

1. Off-domain source rejection across multiple domains, including false-positive/false-negative cases.
2. Full-text/abstract/snippet/metadata labels accurate; partial huge-PDF coverage honestly distinguished.
3. No false `ESTABLISHED` and no citation-ID-only verification.
4. Claim-level A-E gate enforced: citation + relevance + support + depth + quality.
5. No false consensus; opposition search and reasoning completeness requirements respected.
6. Quota/model failure returns a useful incomplete result, never fake completeness or blank boilerplate.
7. Raw provider/protobuf/HTTP traces never leak into the main explanation.
8. Huge PDF processing is bounded-memory AND whole-document sampled when not every page can be inspected.
9. Upload cap stops reading early and cleans partial files.
10. Explicit D-root unavailable/unwritable => fail closed; no silent C: spill.
11. Cloud upload failure/mismatch => local copy preserved; deletion only after verified remote state.
12. Durable job status/result lifecycle, compaction and interrupted restart state all pass.
13. Process lock prevents multiple backend workers from corrupting durable job JSON.
14. Request guard blocks abuse; proxy headers are trusted only when explicitly configured.
15. Full offline regression suite actually executes green on the integrated branch.
16. Live superconductivity benchmark V2 reruns after integration and passes relevance/full-text/hypothesis/error-honesty expectations.
17. Final end-to-end path matches the blueprint: discover -> fetch -> process -> evidence -> reason -> criticize -> hypothesize -> verify -> synthesize -> cite/audit.

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