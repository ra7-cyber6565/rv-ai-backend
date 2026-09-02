# Infinity Research AI — Deployment & Storage Guide

## Hard rules

- Runtime cost target: **₹0**. `ZERO_COST_ONLY=true` stays enabled.
- Never add a paid AI provider as a silent fallback.
- Never commit real API keys, access tokens, client secrets, private secrets, user uploads, research-memory JSON, model files, vector databases, or runtime logs to GitHub.
- Hosting/provider pricing and free-tier limits can change. Verify the provider's current official terms before every deployment; this guide deliberately does **not** promise that any named host is permanently free.

## Laptop setup (recommended while TeraBox API approval is pending)

Create a working folder on D:

```text
D:\InfinityResearchAI
```

In the backend's private `.env` file:

```env
ZERO_COST_ONLY=true
GEMINI_API_KEY=your_real_key_here
# Set true ONLY after checking that every configured Gemini project/key has no
# paid billing or spend path. Without this explicit confirmation startup/live
# testing correctly blocks the key.
GEMINI_ZERO_COST_CONFIRMED=false
INFINITY_DATA_ROOT=D:\InfinityResearchAI
CORS_ALLOWED_ORIGINS=
```

Do **not** put real secrets in `.env.example` or GitHub.

When `INFINITY_DATA_ROOT` is set, the backend routes these heavy/runtime locations below that root:

```text
D:\InfinityResearchAI\
  archive\
  cache\
  knowledge\
  logs\
  models\
  research_memory\
  temp\
  uploads\
  vector_db\
```

This includes ChromaDB, sentence-transformer/Hugging Face/Torch model caches, temporary uploads, research memory, project metadata and archive verification metadata. If the explicitly configured root is unavailable or unwritable, the app fails closed instead of silently moving that workload to C:.

## Run locally

Repository ke backend folder se relative launcher chalao; isme kisi ek user ka
hard-coded `C:\Users\...` path nahi hai:

```powershell
.\START_BACKEND.bat
```

Check:

```text
http://127.0.0.1:8000/health
```

The public health response includes `zero_cost_only` and aggregate storage
readiness/capacity. Security ke liye absolute private filesystem path public
response mein nahi aata. Local console mein launcher ka selected root check karo.

## Cloud deployment

The repository includes `render.yaml`, but a configuration file saying `plan: free` is **not** a guarantee that the vendor's current terms are free. Before deployment:

1. Check the chosen host's current official pricing/quota page.
2. Confirm there is no automatic paid overage/billing path you do not want.
3. Set `ZERO_COST_ONLY=true`.
4. Set `GEMINI_API_KEY` only if the key/project is configured for the genuinely free usage you intend; then set `GEMINI_ZERO_COST_CONFIRMED=true` only after personally verifying there is no paid spend path.
5. Do not set `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` in zero-cost mode; startup deliberately rejects them.
6. Treat container-local disk as temporary unless the host explicitly provides durable storage under terms you have verified.

Cloud start command:

```text
uvicorn main:app --host 0.0.0.0 --port $PORT
```

Health path:

```text
/health
```

## TeraBox archive integration

TeraBox is planned as the large archive layer, but automatic API upload is **not enabled yet**. We are waiting for official developer/API access. No guessed/private endpoint is hard-coded.

Once official credentials are approved, the intended flow is:

```text
D: working file
  -> register SHA-256/size in archive manifest
  -> official TeraBox upload
  -> remote verification
  -> manifest status = VERIFIED
  -> only then may the D: working copy be deleted
```

If upload or verification fails, the local working copy must remain and the item stays pending/failed for retry.

## GitHub's role

GitHub is for source code, tests, configuration templates and version history. It is **not** the bulk-data store. Runtime files and heavy caches are excluded by `.gitignore` going forward.

## Android app

When the backend URL is stable, configure the Android client's base URL to that backend. Keep all provider/API secrets on the backend; never package private API keys inside the Android APK.

## Release validation commands

Run the complete offline gate first. It forcibly blanks cloud credentials and
cannot spend provider quota:

```bat
RUN_FOUNDATION_GATE.bat
```

Check live-test prerequisites without making a live call:

```bat
RUN_LIVE_ZERO_COST_GATE.bat
```

Android Studio ke PowerShell terminal mein recommended command (D: root ko
explicitly validate karta hai):

```powershell
.\RUN_LIVE_ZERO_COST_GATE.ps1 -DataRoot "D:\InfinityResearchAI"
```

Only after the configured provider/account has been confirmed zero-cost, run:

```bat
RUN_LIVE_ZERO_COST_GATE.bat --execute
```

PowerShell equivalent:

```powershell
.\RUN_LIVE_ZERO_COST_GATE.ps1 -Execute -DataRoot "D:\InfinityResearchAI"
```

Provider key command line par mat likho. Real key sirf Git-ignored private
`.env`/backend secret store mein rakho. PowerShell wrapper sirf non-secret data
root aur optional non-secret receipt path arguments forward karta hai.

The live gate requires an explicit `INFINITY_DATA_ROOT`, a currently usable
confirmed/free model layer, a writable absolute runtime root outside the Git
repository, configured minimum free disk space, on-topic/full-text evidence, valid citations,
claim verification, three testable hypotheses, the advanced discovery
assessment, and sanitized public output. Its JSON receipt contains no answer,
source text, URL, prompt or credential. Provider/research execution crash hone
par bhi raw exception public console/receipt mein nahi jaati; a sanitized failure
receipt likhi jaati hai.

The API's structured research result now also includes a `discovery` field with
problem decomposition, evidence graph, conservative novelty screening,
hypothesis ranking, falsification/virtual-experiment plans, calibrated
pre-validation confidence, weakest-link analysis, a bounded next-query loop,
domain requirements and a conservative reality/TRL ladder. These are research
prioritisation aids—not proof, clinical advice or real-world success odds.

After deployment, run the zero-model remote smoke before any live research call:

```powershell
python .\scripts\run_deployed_readonly_smoke.py --execute --base-url "https://YOUR-HOST"
```

This checks public health/privacy, security headers and project capability
isolation without spending model quota. See `docs/RELEASE_SIGNOFF_CHECKLIST.md`
for the same-SHA offline, live, deployment and governance sign-off sequence.
