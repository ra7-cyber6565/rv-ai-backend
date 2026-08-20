import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from api.routes import router as rag_router
from api.agent_routes import router as agent_router
from knowledge.routes import router as knowledge_router
from utils.zero_cost_guard import enforce_zero_cost_config

# Project policy: zero-cost mode is ON by default. If a known paid-provider
# credential is accidentally configured, fail at startup instead of risking a bill.
ZERO_COST_STATUS = enforce_zero_cost_config()

app = FastAPI(
    title="RV AI",
    description="Deep Research Engine — sawaalon ke jawab, source ke saath",
    version="0.2.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# RAG routes — PDF upload & basic Q&A
app.include_router(rag_router, prefix="/api/v1", tags=["RAG"])

# Agent routes — deep multi-step research
app.include_router(agent_router, prefix="/api/v1", tags=["Agents"])

# Knowledge routes — project management
app.include_router(knowledge_router, prefix="/api/v1", tags=["Knowledge"])


WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
INDEX_HTML = os.path.join(WEB_DIR, "index.html")


@app.get("/")
def website():
    """
    RV AI ki website — wahi URL, wahi origin.

    Website ko yahin se serve karne ka faayda: browser aur API ek hi domain par
    hain, isliye na CORS ki dikkat, na kisi config file mein URL likhna padta
    hai. Agar kabhi index.html na mile, to app crash nahi karta — JSON info
    lautata hai.
    """
    if os.path.exists(INDEX_HTML):
        return FileResponse(INDEX_HTML, media_type="text/html")
    return api_info()


@app.get("/api")
def api_info():
    """
    Live endpoint list.

    Pehle yahan haath se likhi hui 5 endpoints ki list thi jo purani ho gayi
    thi (14 registered the). Ab list app ke asli routing table se banti hai,
    isliye ye kabhi jhooth nahi bol sakti — naya endpoint jodo, yahan khud
    dikhega.
    """
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
        "endpoint_count": len(endpoints),
        "endpoints": sorted(endpoints),
    }


@app.get("/health")
def health_check():
    """Health check for cloud deployment platforms (Render, Railway, etc)"""
    return {
        "status": "healthy",
        "service": "RV AI Backend",
        "version": app.version,
        "zero_cost_only": ZERO_COST_STATUS.enabled,
    }
