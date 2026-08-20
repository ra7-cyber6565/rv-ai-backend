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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from api.routes import router as rag_router
from api.agent_routes import router as agent_router
from api.job_routes import router as job_router
from knowledge.routes import router as knowledge_router
from utils.zero_cost_guard import enforce_zero_cost_config
from utils.security_config import allowed_cors_origins

# Project policy: zero-cost mode is ON by default. If a known paid-provider
# credential is accidentally configured, fail at startup instead of risking a bill.
ZERO_COST_STATUS = enforce_zero_cost_config()
CORS_ORIGINS = allowed_cors_origins()

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
    return {
        "message": "RV AI Backend - Production Ready",
        "version": app.version,
        "docs": "/docs",
        "website": "/",
        "zero_cost_only": ZERO_COST_STATUS.enabled,
        "cors_origins": CORS_ORIGINS,
        "storage": storage_status(),
        "endpoint_count": len(endpoints),
        "endpoints": sorted(endpoints),
    }


@app.get("/health")
def health_check():
    """Health check including the configured storage drive."""
    current_storage = storage_status()
    return {
        "status": "healthy" if current_storage.get("available") else "degraded",
        "service": "RV AI Backend",
        "version": app.version,
        "zero_cost_only": ZERO_COST_STATUS.enabled,
        "storage": current_storage,
    }
