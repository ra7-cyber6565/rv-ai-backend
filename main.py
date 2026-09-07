import os
import re

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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from api.routes import router as rag_router
from api.agent_routes import router as agent_router
from api.job_routes import router as job_router
from api.archive_routes import router as archive_router
from api.session_routes import router as session_router
from api.exam_routes import router as exam_router
from api.reading_routes import router as reading_router
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
from utils.release_identity import deployment_revision

ZERO_COST_STATUS = enforce_zero_cost_config()
CORS_ORIGINS = allowed_cors_origins()
RELEASE_STATE = "foundation_verification_pending"
BUILD_REVISION = deployment_revision()

app = FastAPI(
    title="RV AI",
    description="Deep Research Engine — sawaalon ke jawab, source ke saath",
    version="0.2.0"
)

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

_WEB_CSP = (
    "default-src 'self'; "
    "base-uri 'none'; object-src 'none'; frame-ancestors 'none'; "
    "form-action 'self'; connect-src 'self'; "
    "img-src 'self' data: https:; font-src 'self' data:; "
    "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"
)


def _harden_response(response, path: str):
    """Attach privacy/security headers without exposing capability data."""
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    )
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    normalized = str(path or "")
    if normalized.startswith("/api/v1/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers.setdefault("X-Robots-Tag", "noindex, nofollow, noarchive")
    if normalized == "/":
        response.headers.setdefault("Content-Security-Policy", _WEB_CSP)
        response.headers.setdefault("Cache-Control", "no-store, max-age=0")
    return response


@app.middleware("http")
async def protect_free_quota(request: Request, call_next):
    """Bound expensive creation/upload traffic and rapid async-job polling."""
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


app.add_middleware(RequestBodyLimitMiddleware)

app.include_router(session_router, prefix="/api/v1", tags=["Session"])
app.include_router(rag_router, prefix="/api/v1", tags=["RAG"])
app.include_router(agent_router, prefix="/api/v1", tags=["Agents"])
app.include_router(job_router, prefix="/api/v1", tags=["Research Jobs"])
app.include_router(archive_router, prefix="/api/v1", tags=["Archive"])
app.include_router(exam_router, prefix="/api/v1", tags=["Exam Intelligence"])
app.include_router(reading_router, prefix="/api/v1", tags=["Resumable Reading"])
app.include_router(knowledge_router, prefix="/api/v1", tags=["Knowledge"])

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
INDEX_HTML = os.path.join(WEB_DIR, "index.html")


def _runtime_safety_status() -> dict:
    """Aggregate only non-secret/public-safe operational state."""
    return {
        "zero_cost_only": ZERO_COST_STATUS.enabled,
        "release_state": RELEASE_STATE,
        "build_revision": BUILD_REVISION,
        "rate_limit_enabled": rate_limit_enabled(),
        "rate_limiter": limiter.stats(),
        "project_isolation": project_access.status(),
        "reasoning_resilience": reasoning_status(),
        "cloud_archive": provider_status(),
        "storage": public_storage_status(),
    }


def _website_html() -> str:
    """Return the shipped client with honest lifecycle and quality metrics.

    Public users intentionally see only two choices: Chat and Max. Max is the
    single unified research entrypoint; legacy depth/company names stay backend
    compatible but are not separate user decisions.
    """
    with open(INDEX_HTML, "r", encoding="utf-8") as handle:
        html = handle.read()

    html = re.sub(
        r'<div class="modes">.*?</div>',
        '<div class="modes">\n'
        '    <button class="on" data-mode="QUICK">Chat</button>\n'
        '    <button data-mode="MAXIMUM">Max</button>\n'
        '  </div>',
        html,
        count=1,
        flags=re.S,
    )
    html = html.replace(
        "Normal baat ke liye Chat. Sources aur cross-check ke liye Deep/Max; books, archives aur specialist lanes ke liye Marathon.",
        "Normal baat ke liye Chat. Max ek unified full-research run hai: deep search, long research rounds, books/PDFs, specialist agents, validation, red-team aur final synthesis saath chalte hain.",
        1,
    )
    html = html.replace(
        'MAXIMUM:"Max — gehri available research. Isme zyada time lag sakta hai."',
        'MAXIMUM:"Max — unified ultra research: deep search + 5 long rounds + 6 specialist roles (4 core Company roles + 2 extra) + validation, red-team, hypotheses, experiments/backtests jab relevant hon, aur final synthesis. Available evidence/quota ke andar."',
        1,
    )

    html = re.sub(
        r'''["']?COMPLETE["']?\s*:\s*["']Research complete["']''',
        '"COMPLETE":"Research run finished"',
        html,
        count=1,
    )

    helper = '''function qualityMetricLines(data){
  const out=[],ra=(data&&data.research_assurance)||{},cov=(data&&data.coverage)||{};
  const process=Number(ra.research_process_coverage_percent);
  if(Number.isFinite(process))out.push("Research-process coverage: "+process+"% — checklist execution; answer ki truth/quality probability nahi.");
  const sem=(cov.structured_answer_semantic&&typeof cov.structured_answer_semantic==="object")?cov.structured_answer_semantic:{};
  const semantic=Number(sem.semantic_coverage_percent);
  if(Number.isFinite(semantic))out.push("Semantic requested-content coverage: "+semantic+"% — requested parts ki substantive delivery; truth probability nahi.");
  if(out.length===2)out.push("Process % aur semantic % alag metrics hain; process score ko answer-quality/truth score mat maano.");
  return out;
}
'''
    marker = "function auditHtml(split,data){"
    if "function qualityMetricLines(data){" not in html and marker in html:
        html = html.replace(marker, helper + marker, 1)

    anchor = '  if(Array.isArray(data.quality_repairs)&&data.quality_repairs.length)bits.push("Gate repairs: "+joinLabels(data.quality_repairs));'
    metric_line = "  for(const metric of qualityMetricLines(data))bits.push(metric);"
    if metric_line not in html and anchor in html:
        html = html.replace(anchor, anchor + "\n" + metric_line, 1)
    return html


@app.get("/")
def website():
    """RV AI website — same origin as the API."""
    if os.path.exists(INDEX_HTML):
        return HTMLResponse(_website_html())
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
    return {
        "status": "degraded" if degraded else "healthy",
        "service": "RV AI Backend",
        "version": app.version,
        **safety,
    }
