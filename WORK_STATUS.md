# Infinity Research AI — Master Work Status

This file exists so multi-agent work does not forget old decisions or collide.

## Hard rules

- ₹0 only. No paid API/model/service, no silent paid fallback, no surprise billing.
- Secrets stay out of GitHub and Android APK. Backend env/private secret store only.
- Do not bypass paywalls/copyright/access controls.
- Human-first answer: easy Hinglish explanation first; sources/access depth/audit/errors later.
- Evidence honesty: Fact / Evidence / Inference / Hypothesis / Speculation / Unknown must stay distinct.
- `ESTABLISHED` requires genuinely strong/full-text-supported evidence; snippet/abstract-only claims must be downgraded.
- Foundation first. Do not add flashy discovery features until retrieval, relevance, full-text, fallback, verification, UI and tests are reliable.
- Claude and ChatGPT must not edit the same task/files at the same time.

## Current architecture target

Question -> Research Planner -> domain identification -> query expansion -> multi-source discovery -> retrieval -> document/media processing -> evidence extraction -> relevance/source-quality/contradiction checks -> multi-angle reasoning -> hypothesis generation -> criticism/falsification -> verification/math/simulation where possible -> synthesis -> human-first answer -> technical audit.

Storage: GitHub = code/version history; laptop D: = bounded fast working/runtime storage; TeraBox = bulk/archive after official API approval; cloud upload must be verified before local deletion.

## Active work

| Task | Owner | Status | Files / area | Notes |
|---|---|---|---|---|
| Research relevance hardening | Claude | DONE / merged into ChatGPT branch | `research_engine/relevance.py`, planner/query/discovery files | Claude commit `312dcd6`; off-domain hard rejection |
| Source routing + query expansion | Claude | DONE / merged into ChatGPT branch | planner/query/connectors | Domain-aware, deterministic fallback |
| Full-text + large PDF handling | Claude | DONE / merged into ChatGPT branch | content fetch/processing | Chunk/range based; no 4MB blind skip |
| Evidence verification A-E | Claude | STILL PENDING | verification/evidence/claim labels | Citation, relevance, entailment, depth, quality must be completed before foundation pass |
| Consensus/contradiction correctness | Claude | DONE / VERIFY | contradiction/synthesizer | Consensus gate added; needs integrated regression |
| Model quota/fallback honesty | Claude | DONE / VERIFY | Gemini/model reasoning path | Error taxonomy + dynamic discovery; needs integrated regression |
| Superconductivity benchmark V2 | Claude + ChatGPT review | PENDING LIVE RETEST | regression benchmark | Offline fixes landed; live benchmark still required |
| Central D-drive runtime routing | ChatGPT | DONE | `utils/storage_paths.py`, `main.py`, RAG/memory/project paths | Heavy caches/models/vector DB/temp routed under configured root |
| Streaming upload safety | ChatGPT | DONE | `utils/upload_safety.py`, `api/routes.py` | No whole-file RAM buffering, bounded caps, cleanup |
| Upload storage reservation | ChatGPT | DONE / VERIFY | `utils/upload_safety.py`, `utils/storage_quota.py` | HTTP 507 before large write when bounded workspace is unsafe |
| ₹0 startup guard | ChatGPT | DONE | `utils/zero_cost_guard.py`, config | Fail closed on known paid-provider credentials |
| ₹0 request abuse guard | ChatGPT | DONE / VERIFY | `utils/request_guard.py`, `main.py` | Process-local rate limits on expensive POST endpoints |
| Strict browser CORS | ChatGPT | DONE | `utils/security_config.py`, `main.py` | No wildcard CORS |
| Cloud archive manifest | ChatGPT | DONE | `utils/archive_manifest.py` | pending -> uploaded_unverified -> verified; deletion only after verification |
| Provider-neutral cloud storage interface | ChatGPT | DONE foundation | `utils/cloud_storage.py` | Official provider can plug in without core rewrite |
| Async Deep/Maximum research jobs | ChatGPT | DONE / VERIFY | `utils/research_jobs.py`, `api/job_routes.py`, web UI | Avoid giant HTTP timeout; one worker default |
| Durable job result storage | ChatGPT | DONE / VERIFY | `utils/research_jobs.py`, `api/job_routes.py` | Completed results survive restart; in-flight jobs become honest `interrupted` |
| Storage quota / local cleanup safety | ChatGPT | DONE / VERIFY | `utils/storage_quota.py` + tests | Only cloud-VERIFIED local copies eligible for cleanup |
| Runtime/generated files out of Git | ChatGPT | DONE | `.gitignore` | Research memory/db/cache/generated data should not be committed |
| Deployment docs ₹0 cleanup | ChatGPT | DONE | `DEPLOYMENT_GUIDE.md`, `.env.example` | Current safety/config knobs documented |
| TeraBox official adapter | ChatGPT | BLOCKED | future provider module | Waiting for official TeraBox API credentials/approval; no unofficial reverse-engineered client |
| Encryption for cloud archive | ChatGPT | BLOCKED ON SAFE KEY DESIGN / PROVIDER | storage/security | Do not deploy encryption that risks unrecoverable data; key must stay out of repo/APK |
| Secondary compact metadata backup | ChatGPT | PLANNED AFTER PROVIDER APPROVAL | storage/provider layer | Small critical metadata only; genuinely free destination required |
| Integrated regression after branch merge | ChatGPT | REQUIRED | full branch | Local clone unavailable in current tool environment; do not falsely claim tests passed |

## Required test gates before foundation is considered reliable

1. Off-domain source rejection.
2. Full-text/abstract/snippet labels accurate.
3. No false `ESTABLISHED`.
4. No false consensus.
5. Quota/model failure returns useful incomplete result, not blank templates.
6. Raw provider/protobuf/HTTP trace never leaks into main answer.
7. Large PDF chunk processing works.
8. Upload cap stops reading early and cleans partial file.
9. D-drive/root unavailable => fail closed, no silent C: fallback when explicitly configured.
10. Cloud upload failure/mismatch => local copy preserved.
11. Async + durable job status/result lifecycle works, including `interrupted` restart state.
12. Request rate guard blocks abuse without trusting spoofed proxy headers by default.
13. Full regression suite + superconductivity benchmark rerun after integration.
14. Evidence verification A-E completed and enforced.

## Advanced Scientific Discovery Engine — intentionally postponed until foundation passes

These are remembered requirements, not forgotten features:

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

Each generated hypothesis eventually needs support, counter-evidence, assumptions, unknowns, falsification criteria, required experiment/simulation, expected impact and calibrated confidence. Never promise arbitrary 90-95% real-world success.

## UI/product requirements remembered

- Modes: Quick / Deep / Maximum / Custom.
- Real progress/stages, not fake percentages.
- Sources may include uploaded docs + legally/publicly accessible papers, books, reports, patents, datasets, webpages, video/audio transcripts.
- Main response should not be cluttered by raw logs/DOIs/errors.
- Answer first in easy teacher-like Hinglish; technical source/audit layer afterward.
- Android should remain a thin client; provider secrets stay backend-side.

## Coordination rule

Before starting a task, check this file. If another agent owns a task/file marked ACTIVE, do not edit it. After each major batch, commit + push and record the commit SHA/status here.
