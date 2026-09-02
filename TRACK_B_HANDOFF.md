# Infinity Research AI — Track B External-Proof Handoff

## Authority and base

- Repository: `ra7-cyber6565/rv-ai-backend`
- Track-B branch: `chatgpt-track-b-external-proof-20260902`
- Immutable split base: `fcd9458c7601fc2b485f291854addfa549377aa9`
- Track-A branch is owned by the primary ChatGPT workstream. Do **not** push Track-B work to Track-A or `main`.
- Never claim 142/142, VERIFIED, 100/100, tested, live, independent, hardware-validated, or safe unless the corresponding proof class is actually produced and accepted by the strict auditor.

## Non-negotiable epistemic laws

1. No evidence -> no strong claim.
2. No execution -> no `tested` claim.
3. No independent validation -> no `verified` claim.
4. No benchmark -> no 90-95% or similar effectiveness claim.
5. Unknown is an acceptable result.
6. A software simulator or callback is not physical hardware evidence.
7. A second process on the same implementation is not automatically independent replication.
8. A local HMAC key is not production KMS evidence.
9. A locally stored anchor is not independently retained anti-rollback evidence.
10. Green CI may prove the exact test/code contract only; it must not be promoted into LIVE/HARDWARE/INDEPENDENT/SAFETY evidence without an explicit trusted attestor for that proof class.

## Stage model

- Stage A: 142/142 software foundations MAX
- Stage B: 142/142 production wiring MAX
- Stage C: 142/142 adversarial/benchmark tests MAX
- Stage D: execution/reproducibility MAX
- Stage E: independent/live/hardware evidence MAX
- Stage F: strict auditor says 142/142 VERIFIED = 100/100

Track B primarily owns **Stage D/E external-proof infrastructure**. Track A owns remaining general software/wiring/adversarial capability work and the final integration/auditor merge.

## Track-B owned work

Build and harden infrastructure for evidence that cannot honestly be produced by source code alone. Prefer new isolated modules and tests; reuse existing primitives rather than replacing them.

### B1 — Protected external secret / anchor provider interface

Create an adapter-neutral trust boundary for proof-ledger keys and independently retained anchors:

- provider protocol with explicit capabilities (`sign`, `verify`, `store_anchor`, `read_anchor`, version/identity)
- no secret bytes returned to ordinary research code
- key identifiers/version, rotation metadata, rollback-resistant sequence expectations
- provider identity fingerprint in receipts
- test provider for CI that is loudly marked simulated/non-production
- production adapters should be interfaces/config only unless real credentials/provider are available
- adversarial tests: wrong key id, stale anchor, rollback, provider substitution, missing identity, replay, downgrade, malformed token, concurrent update conflict
- never mark KMS/independent-anchor proof from in-memory/local-file test provider

### B2 — Real live-deployment evidence protocol

Build a provider-neutral runtime observation harness that can attest long-running deployed behavior without fabricating live status:

- deployment identity and immutable build revision
- UTC observation windows with minimum duration/count policy
- heartbeat/gap detection
- request/outcome counters
- error-rate/latency/resource summaries with bounded inputs
- deployment restart/epoch tracking
- signed observation receipt envelope
- explicit environment identity (staging/prod/test)
- test/synthetic observations always labelled non-live
- LIVE receipt minting must require a separately trusted operator/adaptor and policy-approved environment identity
- adversarial tests for clock rollback, duplicated windows, overlapping epochs, missing intervals, revision mismatch, replayed receipts, synthetic provider falsely requesting LIVE

### B3 — Physical sensor/hardware execution evidence protocol

Extend the existing physical-lab boundary/attestors rather than replacing them:

- hardware device identity and calibration certificate references
- sensor identity, units, range, sampling frequency, uncertainty, calibration age
- apparatus/firmware/software revision bindings
- operator/supervisor identity roles
- interlock/emergency-stop evidence
- command -> acknowledgement -> measurement causal chain
- raw sample commitment/hash + bounded summary
- safety incident/abort receipt
- hardware evidence must remain impossible to mint from callbacks/simulators/test doubles
- adversarial tests for duplicated sensor id, stale calibration, unit mismatch, impossible timestamps, missing interlock, firmware mismatch, replayed samples, simulator masquerading as device, operator self-approval when two roles required

### B4 — Independent replication / physically independent runner protocol

Harden independence beyond `different runner_id`:

- implementation digest/family
- model/provider identity
- machine/host identity attestation field
- operator/team identity field
- data/holdout independence declaration
- environment/container/build identity
- preregistered protocol hash
- result commitment before reveal when blind evaluation is required
- configurable minimum distinct implementation/provider/host/operator thresholds
- independence matrix and reasoned failure diagnostics
- test doubles may exercise code but cannot mint real INDEPENDENT proof
- adversarial tests for renamed same implementation, same host aliases, same model under two labels, shared holdout leakage, colluding pre-reveal result, duplicated operator identities

### B5 — Real production traffic / post-deployment validation evidence

Build trusted ingestion around existing post-deployment validation:

- production traffic provenance envelope
- privacy-preserving IDs/aggregates
- build/deployment revision binding
- data-window commitments
- label/outcome delay handling (`no outcomes` != validated)
- distribution-shift/performance-drift observation receipts
- champion/challenger observation identity
- alert/incident linkage
- synthetic/replay data must never qualify as production traffic

### B6 — External third-party replication package protocol

Build export/import/verification for third-party replication without trusting self-asserted JSON:

- deterministic reproducibility capsule reference
- preregistered protocol + environment requirements
- verifier public identity/fingerprint
- detached signed result envelope interface
- independent timestamp/reference
- result/metric commitments
- contradiction/disagreement preservation
- invalid/unknown signature/provider -> no INDEPENDENT receipt
- do not implement a fake `third party` provider in production path

## Track-B file ownership / conflict rules

To prevent corruption and merge conflicts:

1. Prefer **new files** under:
   - `research_engine/external_proof/`
   - `tests/external_proof/`
   - `config/external_proof/`
   - `scripts/external_proof/`
2. Do **not** edit these shared integration files on Track B unless the handoff is explicitly updated:
   - `research_engine/__init__.py`
   - `research_engine/orchestrator.py`
   - `research_engine/models.py`
   - `research_engine/capability_registry.py`
   - `research_engine/maturity_proof.py`
   - `research_engine/maturity_auditor.py`
   - `research_engine/maturity_attestor.py`
   - `config/maturity_proof_policy.json`
   - `config/maturity_attestor_registry.json`
   - `.github/workflows/foundation-tests.yml`
3. If shared wiring is needed, record the exact proposed change in `TRACK_B_MERGE_PLAN.json` instead of editing the shared file.
4. Do not delete or weaken existing tests. Do not modify a test merely to make a failing implementation green.
5. Before each write, verify Track-B branch head so concurrent edits are not overwritten.

## Required Track-B outputs

Track B is not complete until it has:

- isolated production-quality modules for B1-B6 where feasible
- explicit provider protocols and trust boundaries
- fail-closed schemas/budgets/UTC/revision binding
- adversarial unit + integration tests
- deterministic receipts/hashes where appropriate
- simulation/test providers visibly labelled `non_production`
- `TRACK_B_MERGE_PLAN.json` listing every shared registry/wiring/workflow change Track A must perform
- `TRACK_B_STATUS.md` with exact completed/incomplete/external blockers
- no claim of real live/hardware/independent evidence unless an actual external resource was used and its proof is present

## Merge acceptance gate

Track A should merge Track B only after:

1. clean diff from split base
2. no unauthorized shared-file edits
3. Track-B tests pass
4. full Foundation suite passes after integration
5. proof-policy/auditor tests pass
6. no proof-class escalation from synthetic/test providers
7. current exact Git revision is bound in receipts
8. final strict auditor still reports external blockers honestly

## Prompt for the second ChatGPT

Use this exact instruction:

> Work only on branch `chatgpt-track-b-external-proof-20260902` of `ra7-cyber6565/rv-ai-backend`, based on split SHA `fcd9458c7601fc2b485f291854addfa549377aa9`. Read `TRACK_B_HANDOFF.md` completely before editing. You own only the Track-B external-proof work described there. Do not edit Track-A/shared files listed as prohibited; put required shared integration changes in `TRACK_B_MERGE_PLAN.json`. Build as much of B1-B6 as can be implemented honestly, with fail-closed trust boundaries and adversarial tests. Never fabricate LIVE/HARDWARE/INDEPENDENT/KMS/third-party evidence. Continue until the software/protocol work in your track is maximally hardened or an actual external-resource blocker is reached. At the end write `TRACK_B_STATUS.md` with exact commits, tests, remaining external blockers, and no inflated 100/100 claim.
