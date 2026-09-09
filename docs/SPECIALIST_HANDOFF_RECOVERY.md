# Specialist handoff recovery boundary

The live Max acceptance run observed one `specialist_handoff` failure, leaving 10/11 reasoning passes. This document records the bounded recovery rule added on PR #81.

## Safety rule

- Retry only an explicit specialist-handoff transport/orchestration failure.
- Retry at most once.
- Never retry or hide substantive quality, evidence, validation, disagreement, or model failures.
- Never fabricate a specialist response.
- A second failure remains failed/PARTIAL eligible.
- Recovery is successful only when a real subsequent invocation satisfies the caller's success predicate.

## Current integration status

The reusable recovery primitive and focused honesty tests are implemented on the PR branch. Wiring it into the production company handoff call-site must be verified against the exact orchestrator/worker producer before the defect can be called integrated or fixed. Until then this item is **IMPLEMENTED / VERIFICATION PENDING**, not COMPLETE.
