from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router as rag_router
from api.agent_routes import router as agent_router
from knowledge.routes import router as knowledge_router

app = FastAPI(
    title="Infinity Research AI",
    description="Deep Research Engine — PDF se sawaalon ke jawab, source ke saath",
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


@app.get("/")
def root():
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
        "message": "RV AI Backend - Production Ready ✅",
        "version": app.version,
        "docs": "/docs",
        "endpoint_count": len(endpoints),
        "endpoints": endpoints[:10]
    }

@app.get("/health")
def health_check():
    """Health check for cloud deployment platforms (Render, Railway, etc)"""
    return {"status": "healthy", "service": "RV AI Backend", "version": app.version}

