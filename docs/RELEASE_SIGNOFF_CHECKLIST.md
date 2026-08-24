# Release sign-off checklist

Production sign-off is evidence tied to one exact Git commit. Offline CI, a
live confirmed-zero-cost research run and deployment checks prove different
things; none may be substituted for another.

## 1. Preserve unrelated local work

Before pulling, inspect the Windows checkout:

```powershell
git status --short
git stash list
```

If Claude or the user has uncommitted work, commit it on its own branch or stash
it with a clear name before pulling. Do not discard, overwrite or mix that work
into a release test branch.

```powershell
git pull --ff-only origin main
git rev-parse HEAD
```

Record the full SHA. Every receipt below must be produced from that same SHA.
The runners now record and verify the full revision automatically and fail
closed on a dirty checkout; do not hand-edit a receipt to make revisions match.

## 2. Strict offline Foundation gate

```powershell
.\RUN_FOUNDATION_GATE.bat
```

Required result: every stage passes, including focused and full pytest,
provider-bypass/source-boundary/architecture audits, offline API smoke, core
regression and both adversarial science benchmarks. A benchmark score is a
software-contract result, not proof of scientific truth.

## 3. Confirmed ₹0 live research gate

No-call preflight first:

```powershell
.\RUN_LIVE_ZERO_COST_GATE.ps1 -DataRoot "D:\InfinityResearchAI"
```

Only after personally confirming that the configured project/key has no paid
spend path:

```powershell
.\RUN_LIVE_ZERO_COST_GATE.ps1 -Execute -DataRoot "D:\InfinityResearchAI"
```

Required result: `LIVE ZERO-COST GATE: PASS`. Keep the sanitized receipt. Never
paste API keys into a command, receipt, chat, GitHub issue or commit.

## 4. Deployed zero-model smoke

The deployment URL is not stored in the repository. Preflight makes no request:

```powershell
python .\scripts\run_deployed_readonly_smoke.py --base-url "https://YOUR-HOST" 
```

Execute the bounded smoke after inserting the real HTTPS origin:

```powershell
python .\scripts\run_deployed_readonly_smoke.py --execute --base-url "https://YOUR-HOST" --receipt "D:\InfinityResearchAI\audit\deployed_readonly_smoke.json"
```

If a separately hosted frontend has an allowed CORS origin, verify exact-origin
behaviour too:

```powershell
python .\scripts\run_deployed_readonly_smoke.py --execute --base-url "https://YOUR-HOST" --expected-origin "https://YOUR-FRONTEND" --receipt "D:\InfinityResearchAI\audit\deployed_readonly_smoke.json"
```

This gate makes no model/research/upload call. It checks health, honest release
state, zero-cost mode, public metadata privacy, processing capability reporting,
session capability issuance, private no-store headers, rejection without a
capability and acceptance with the capability. The receipt omits the issued
project ID/token. Railway supplies `RAILWAY_GIT_COMMIT_SHA` for a
GitHub-triggered deployment; `/health` exposes only that validated full SHA as
`build_revision`, and this smoke fails when it differs from the clean checkout.

## 5. Exact-revision proof bundle

After all three receipts exist, verify them together. This makes a mixed-commit
"green" release fail closed and writes only receipt hashes/booleans/the Git SHA:

```powershell
python .\scripts\verify_release_bundle.py `
  --foundation "D:\InfinityResearchAI\audit\foundation_gate_latest.json" `
  --live "D:\InfinityResearchAI\audit\live_zero_cost_gate_latest.json" `
  --deployed "D:\InfinityResearchAI\audit\deployed_readonly_smoke.json" `
  --output "D:\InfinityResearchAI\audit\release_signoff_bundle.json"
```

Required result: `EXACT-REVISION RELEASE BUNDLE: PASS`.

## 6. Deployment restart/recovery

The operator must still prove host-specific behaviour:

1. Create a disposable project/session and record only non-secret test IDs in a
   private operator log.
2. Restart/redeploy the service using the same durable volume configuration.
3. Re-run health and the zero-model smoke.
4. Run one explicitly authorised confirmed-zero-cost research job; verify
   capability-protected progress/result retrieval and timeout behaviour.
5. Restart during a disposable job and verify that interrupted state is marked
   honestly, not reported as complete.
6. Confirm runtime data is on the intended persistent root and no absolute path
   appears in public responses.

These steps depend on the actual host, volume and provider account and therefore
cannot be truthfully certified by repository CI alone.

## 7. GitHub governance

Enable branch protection/rules for `main` in GitHub settings:

- require a pull request before merging;
- require the `Foundation tests / offline-regression` check;
- require the branch to be up to date before merge;
- block force pushes and deletion; and
- restrict bypass permissions to the smallest operator set.

Repository code cannot grant its own branch protection. Verify the rule in the
GitHub UI/API after saving it; do not infer protection from a workflow file.

## 8. Optional archives

Google Drive archive remains optional and requires the user's official OAuth/
rclone configuration. TeraBox stays blocked until official API credentials and
current zero-cost terms are confirmed. Encryption stays blocked until a
recoverable key-management design exists. Remote verification must complete
before any local working copy may be deleted.

## Sign-off rule

Release can be approved only when all required receipts/checks above refer to
the same current SHA and no unresolved high-severity failure remains. Even then,
say exactly what was tested; do not advertise “100% correct,” guaranteed novel
research, examiner mind-reading or a 90–95% real-world success probability.
