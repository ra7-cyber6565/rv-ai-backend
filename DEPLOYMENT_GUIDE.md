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

```bat
cd C:\Users\intel\Music\infinity-research-ai-main\infinity-research-ai-main\backend
venv\Scripts\activate
python -m uvicorn main:app --reload
```

Check:

```text
http://127.0.0.1:8000/health
```

The health response includes `zero_cost_only` and storage status. Confirm that the reported storage root is the intended D: location before large uploads or model downloads.

## Cloud deployment

The repository includes `render.yaml`, but a configuration file saying `plan: free` is **not** a guarantee that the vendor's current terms are free. Before deployment:

1. Check the chosen host's current official pricing/quota page.
2. Confirm there is no automatic paid overage/billing path you do not want.
3. Set `ZERO_COST_ONLY=true`.
4. Set `GEMINI_API_KEY` only if the key/project is configured for the genuinely free usage you intend.
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
