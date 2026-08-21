import os

# .env must be loaded BEFORE storage routing. Otherwise a laptop setting such as
# INFINITY_DATA_ROOT=D:\InfinityResearchAI would be seen too late and caches
# could already have chosen the system drive.
from dotenv import load_dotenv
load_dotenv()

# Storage paths must be configured before heavy libraries (transformers/chromadb)
# are imported so their caches/models do not silently land on C:.
from utils.storage_paths import configure_process_storage, storage_status
STORAGE_STATUS = configure_process_storage()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from api.routes import router as rag_router
from api.agent_routes import router as agent_router
from api.job_routes import router as job_router
from knowledge.routes import router as knowledge_router
from storage.provider_factory import provider_status
from utils.zero_cost_guard import enforce_zero_cost_config
from utils.security_config import allowed_cors_origins
from utils.request_guard import client_key, enabled as rate_limit_enabled, limit_for, limiter
from utils.reasoning_status import reasoning_status

# Project policy: zero-cost mode is ON by default. If a known paid-provider
# credential is accidentally configured, fail at startup instead of risking a bill.
ZERO_COST_STATUS = enforce_zero_cost_config()
CORS_ORIGINS = allowed_cors_origins()

# This value is deliberately honest. It must not be changed to "production_ready"
# until the integrated offline gate, live zero-cost benchmark and final review have
# actually passed. Runtime health and release readiness are different concepts.
RELEASE_STATE = os.getenv("INFINITY_RELEASE_STATE", "foundation_verification_pending").strip() \
    or "foundation_verification_pending"

app = FastAPI(
    title="RV AI",
    description="Deep Research Engine — sawaalon ke jawab, source ke saath",
    version="0.2.0"
)

# Website isi FastAPI origin se serve hoti hai, isliye browser CORS default se
# closed rakha gaya hai. Separate frontend ho to CORS_ALLOWED_ORIGINS mein exact
# http(s) origins comma-separated set karo; wildcard deliberately reject hota hai.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.middleware("http")
async def protect_free_quota(request: Request, call_next):
    """Bound expensive POST endpoints so a public deployment cannot burn free quota.

    This limiter is process-local and intentionally modest. It adds no paid
    infrastructure and can be disabled with RATE_LIMIT_ENABLED=false for local
    development. Proxy headers are trusted only when TRUST_PROXY_HEADERS=true.
    """
    if rate_limit_enabled():
        limit = limit_for(request.method, request.url.path)
        if limit is not None:
            allowed, retry_after = limiter.check(
                client_key(request), request.url.path, limit
            )
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Free quota protection: bahut requests aa gayi hain. Thodi der baad dobara try karein.",
                        "retry_after_seconds": retry_after,
                    },
                    headers={"Retry-After": str(retry_after)},
                )
    return await call_next(request)

# RAG routes — upload & basic Q&A
app.include_router(rag_router, prefix="/api/v1", tags=["RAG"])

# Agent routes — existing synchronous research/chat API
app.include_router(agent_router, prefix="/api/v1", tags=["Agents"])

# Job routes — preferred for long DEEP/MAXIMUM runs so HTTP timeout does not
# throw away the user's ability to fetch the eventual result.
app.include_router(job_router, prefix="/api/v1", tags=["Research Jobs"])

# Knowledge routes — project management
app.include_router(knowledge_router, prefix="/api/v1", tags=["Knowledge"])


WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
INDEX_HTML = os.path.join(WEB_DIR, "index.html")


def _runtime_safety_status() -> dict:
    """Aggregate only non-secret operational state for API/health responses."""
    return {
        "zero_cost_only": ZERO_COST_STATUS.enabled,
        "release_state": RELEASE_STATE,
        "rate_limit_enabled": rate_limit_enabled(),
        "rate_limiter": limiter.stats(),
        "reasoning_resilience": reasoning_status(),
        "cloud_archive": provider_status(),
        "storage": storage_status(),
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
    """Health check including storage and non-secret archive/reasoning readiness."""
    safety = _runtime_safety_status()
    current_storage = safety["storage"]
    archive = safety["cloud_archive"]
    degraded = not current_storage.get("available")
    # Cloud archive is optional when disabled. If explicitly enabled but not
    # ready, surface degraded health without crashing the research API.
    if archive.get("enabled") and not archive.get("ready"):
        degraded = True
    # Hosted/free reasoning providers are intentionally NOT a health-failure
    # condition: deterministic local evidence fallback remains available even if
    # every cloud quota is exhausted. The detailed non-secret readiness is still
    # exposed under reasoning_resilience for diagnostics/UI.
    return {
        "status": "degraded" if degraded else "healthy",
        "service": "RV AI Backend",
        "version": app.version,
        **safety,
    }
