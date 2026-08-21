import os

# .env must be loaded BEFORE storage routing. Otherwise a laptop setting such as
# INFINITY_DATA_ROOT=D:\InfinityResearchAI would be seen too late and caches
# could already have chosen the system drive.
from dotenv import load_dotenv
load_dotenv()

# Storage paths must be configured before heavy libraries (transformers/chromadb)
# are imported so their caches/models do not silently land on C:.
from utils.storage_paths import configure_process_storage, public_storage_status
STORAGE_STATUS = configure_process_storage()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from api.routes import router as rag_router
from api.agent_routes import router as agent_router
from api.job_routes import router as job_router
from api.archive_routes import router as archive_router
from api.session_routes import router as session_router
from knowledge.routes import router as knowledge_router
from storage.provider_factory import provider_status
from utils.body_limit import RequestBodyLimitMiddleware
from utils.zero_cost_guard import enforce_zero_cost_config
from utils.security_config import allowed_cors_origins
from utils.request_guard import (
    bucket_for,
    client_key,
    enabled as rate_limit_enabled,
    limit_for,
    limiter,
)
from utils.reasoning_status import reasoning_status
from utils.project_access import project_access

ZERO_COST_STATUS = enforce_zero_cost_config()
CORS_ORIGINS = allowed_cors_origins()
RELEASE_STATE = "foundation_verification_pending"

app = FastAPI(
    title="RV AI",
    description="Deep Research Engine — sawaalon ke jawab, source ke saath",
    version="0.2.0"
)

# Same-origin website needs no CORS grant. A separately-hosted approved frontend
# may use exact configured origins and opaque project/job capability headers.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "X-Project-Token",
        "X-Research-Job-Token",
        "X-Infinity-Admin-Token",
    ],
)
# This pure-ASGI guard is intentionally added after CORS so it is outermost in
# Starlette's user middleware stack. It counts raw bytes before JSON/multipart
# parsing, closing the gap where a huge chunked upload could spool before the
# route-level UploadFile size check ever runs.
app.add_middleware(RequestBodyLimitMiddleware)


def _harden_response(response, path: str):
    """Attach cheap privacy/security headers without exposing capability data.

    `/api/v1` includes responses that can contain newly-issued project/job bearer
    capabilities, research text, document metadata and private progress. Custom
    bearer headers are not the same as standard HTTP Authorization semantics for
    every intermediary, so explicitly forbid caching instead of trusting proxies
    or browser defaults. This also covers validation/rate-limit responses.
    """
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    if str(path or "").startswith("/api/v1/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


@app.middleware("http")
async def protect_free_quota(request: Request, call_next):
    """Bound expensive creation/upload traffic and rapid async-job polling.

    Dynamic job ids are normalized to one rate bucket per client so legitimate
    polling works while a flood of random job-id URLs cannot explode limiter
    memory. Proxy headers remain untrusted unless explicitly enabled.
    """
    if rate_limit_enabled():
        limit = limit_for(request.method, request.url.path)
        if limit is not None:
            allowed, retry_after = limiter.check(
                client_key(request),
                bucket_for(request.method, request.url.path),
                limit,
            )
            if not allowed:
                response = JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Free quota/server protection: bahut requests aa gayi hain. Thodi der baad dobara try karein.",
                        "retry_after_seconds": retry_after,
                    },
                    headers={"Retry-After": str(retry_after)},
                )
                return _harden_response(response, request.url.path)
    response = await call_next(request)
    return _harden_response(response, request.url.path)

# Session is zero-model/zero-cloud and creates a random isolated project namespace.
app.include_router(session_router, prefix="/api/v1", tags=["Session"])
app.include_router(rag_router, prefix="/api/v1", tags=["RAG"])
app.include_router(agent_router, prefix="/api/v1", tags=["Agents"])
app.include_router(job_router, prefix="/api/v1", tags=["Research Jobs"])
app.include_router(archive_router, prefix="/api/v1", tags=["Archive"])
app.include_router(knowledge_router, prefix="/api/v1", tags=["Knowledge"])


WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
INDEX_HTML = os.path.join(WEB_DIR, "index.html")


def _runtime_safety_status() -> dict:
    """Aggregate only non-secret/public-safe operational state.

    Keep /health cheap: hosting platforms may call it frequently, so it must not
    recursively scan a large D: workspace. Detailed manifest/retry/storage
    archive state lives at the admin-only /api/v1/archive/status endpoint.
    """
    return {
        "zero_cost_only": ZERO_COST_STATUS.enabled,
        "release_state": RELEASE_STATE,
        "rate_limit_enabled": rate_limit_enabled(),
        "rate_limiter": limiter.stats(),
        "project_isolation": project_access.status(),
        "reasoning_resilience": reasoning_status(),
        "cloud_archive": provider_status(),
        # Never expose STORAGE_STATUS/storage_status() directly: internal status
        # includes absolute filesystem paths and may include raw OS error text.
        "storage": public_storage_status(),
    }


@app.get("/")
def website():
    """RV AI website — same origin as the API."""
    if os.path.exists(INDEX_HTML):
        return FileResponse(INDEX_HTML, media_type="text/html")
    return api_info()


@app.get("/api")
def api_info():
    """Live endpoint list + important runtime safety state."""
    endpoints = []
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = sorted(getattr(route, "methods", set()) - {"HEAD", "OPTIONS"})
        if path.startswith("/api/") and methods:
            endpoints.append(f"{','.join(methods)} {path}")
    safety = _runtime_safety_status()
    return {
        "message": "RV AI Backend - foundation integration build",
        "version": app.version,
        "docs": "/docs",
        "website": "/",
        **safety,
        "cors_origins": CORS_ORIGINS,
        "endpoint_count": len(endpoints),
        "endpoints": sorted(endpoints),
    }


@app.get("/health")
def health_check():
    """Health check including public-safe storage/archive/security readiness."""
    safety = _runtime_safety_status()
    current_storage = safety["storage"]
    archive = safety["cloud_archive"]
    project_isolation = safety["project_isolation"]
    degraded = not current_storage.get("available")
    if archive.get("enabled") and not archive.get("ready"):
        degraded = True
    if not project_isolation.get("project_capability_tokens_ready"):
        degraded = True
    # Hosted/free reasoning providers are not a health-failure condition because
    # deterministic local evidence fallback remains available.
    return {
        "status": "degraded" if degraded else "healthy",
        "service": "RV AI Backend",
        "version": app.version,
        **safety,
    }
