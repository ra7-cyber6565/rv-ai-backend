"""Static architecture audit for Infinity Research AI.

This is not a substitute for runtime tests. It is a deterministic, zero-cost
release gate that catches a different class of regression: a refactor can leave
individual unit tests green while accidentally disconnecting a whole capability
from the real application path.

The audit therefore checks that the production entrypoint is still wired as:

    API -> research manager/orchestrator -> discover -> read/process -> evidence
    -> reasoning/fallback -> claim verification -> citations -> verification
    -> human-first synthesizer/audit

It also checks the project's hard safety invariants (₹0 provider guard, local
fallback, provider cooldown memory, strict CORS, anonymous project namespace
capabilities, private async-job capabilities, bounded storage/jobs, honest release
state, no obvious committed secrets).

Exit code:
    0  all required checks pass
    1  one or more required checks fail

No network, API key, model or external service is used.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List, Sequence


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class AuditCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class AuditReport:
    schema_version: int
    passed: bool
    checks: list[dict]
    failed: list[str]


def _read(path: str) -> str:
    target = ROOT / path
    try:
        return target.read_text(encoding="utf-8")
    except Exception:
        return ""


def _exists(path: str) -> bool:
    return (ROOT / path).is_file()


def _contains(path: str, *needles: str) -> AuditCheck:
    text = _read(path)
    missing = [needle for needle in needles if needle not in text]
    return AuditCheck(
        name=f"wiring:{path}",
        passed=bool(text) and not missing,
        detail=("required wiring present" if text and not missing
                else "missing: " + ", ".join(missing or ["file unreadable"])),
    )


def _ordered(path: str, labels: Sequence[tuple[str, str]]) -> AuditCheck:
    """Require important pipeline markers to occur in the expected order."""
    text = _read(path)
    positions: List[tuple[str, int]] = []
    for label, needle in labels:
        positions.append((label, text.find(needle)))
    missing = [label for label, pos in positions if pos < 0]
    monotonic = all(
        positions[index][1] < positions[index + 1][1]
        for index in range(len(positions) - 1)
        if positions[index][1] >= 0 and positions[index + 1][1] >= 0
    )
    return AuditCheck(
        name=f"pipeline-order:{path}",
        passed=bool(text) and not missing and monotonic,
        detail=(" -> ".join(label for label, _ in positions)
                if not missing and monotonic else
                f"missing={missing}; positions={dict(positions)}"),
    )


def _required_files(paths: Iterable[str]) -> AuditCheck:
    missing = [path for path in paths if not _exists(path)]
    return AuditCheck(
        name="required-production-and-test-files",
        passed=not missing,
        detail="all present" if not missing else "missing: " + ", ".join(missing),
    )


def _no_wildcard_cors() -> AuditCheck:
    joined = _read("main.py") + "\n" + _read("utils/security_config.py")
    bad_patterns = (
        'allow_origins=["*"]',
        "allow_origins=['*']",
        'CORS_ALLOWED_ORIGINS="*"',
        "CORS_ALLOWED_ORIGINS='*'",
    )
    found = [pattern for pattern in bad_patterns if pattern in joined]
    return AuditCheck(
        name="security:no-wildcard-cors",
        passed=not found and "allowed_cors_origins" in joined,
        detail="exact-origin CORS guard present" if not found else f"unsafe: {found}",
    )


def _release_honesty() -> AuditCheck:
    text = _read("main.py")
    bad = "RV AI Backend - Production Ready" in text
    required = (
        "foundation_verification_pending",
        '"release_state": RELEASE_STATE',
        '"status": "degraded" if degraded else "healthy"',
    )
    missing = [needle for needle in required if needle not in text]
    return AuditCheck(
        name="honesty:release-state-not-faked",
        passed=bool(text) and not bad and not missing,
        detail=(
            "runtime health is separate from release readiness"
            if text and not bad and not missing
            else f"production_ready_claim={bad}; missing={missing}"
        ),
    )


def _zero_cost_chain() -> AuditCheck:
    guard = _read("utils/zero_cost_guard.py")
    router = _read("research_engine/reasoning_router.py")
    env = _read(".env.example")
    required_guard = (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_ZERO_COST_CONFIRMED",
        "GROQ_ZERO_COST_CONFIRMED",
        "OPENROUTER_MODEL",
        "OLLAMA_BASE_URL",
    )
    required_router = (
        "openrouter/free",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
        "OLLAMA_ENABLED",
        "_local_ollama_url",
    )
    required_env = (
        "ZERO_COST_ONLY=true",
        "REASONING_FALLBACK_CHAIN=groq,openrouter,ollama",
        "GEMINI_ZERO_COST_CONFIRMED=false",
        "GROQ_ZERO_COST_CONFIRMED=false",
        "OPENROUTER_MODEL=openrouter/free",
        "OLLAMA_ENABLED=false",
    )
    missing = (
        [f"guard:{x}" for x in required_guard if x not in guard]
        + [f"router:{x}" for x in required_router if x not in router]
        + [f"env:{x}" for x in required_env if x not in env]
    )
    return AuditCheck(
        name="safety:zero-cost-provider-chain",
        passed=not missing,
        detail="fail-closed free-provider routing present" if not missing else "missing: " + ", ".join(missing),
    )


def _foundation_workflow_safe() -> AuditCheck:
    """Catch expressions that GitHub rejects before any CI job can start."""
    text = _read(".github/workflows/foundation-tests.yml")
    required = (
        "ubuntu-latest",
        "scripts/run_foundation_gate.py",
        "pull_request:\n    branches: [main]",
        "INFINITY_DATA_ROOT: /tmp/rv-ai-infinity-data",
    )
    missing = [needle for needle in required if needle not in text]
    push_block = re.search(r"(?ms)^  push:\s*\n(?P<body>(?: {4}.*\n?)*)", text)
    main_push = bool(
        push_block
        and re.search(r"(?m)^    branches:\s*\[[^\]]*\bmain\b",
                      push_block.group("body"))
    )
    if not main_push:
        missing.append("push trigger for main")
    node24_actions = {
        "actions/checkout": re.search(
            r"actions/checkout@v(?:[5-9]|[1-9]\d+)\b", text
        ),
        "actions/setup-python": re.search(
            r"actions/setup-python@v(?:[6-9]|[1-9]\d+)\b", text
        ),
    }
    legacy_actions = [name for name, match in node24_actions.items() if not match]
    if legacy_actions:
        missing.append(
            "Node 24-compatible action major(s): " + ", ".join(legacy_actions)
        )
    invalid_job_env = "INFINITY_DATA_ROOT: ${{ runner." in text
    return AuditCheck(
        name="ci:foundation-workflow-valid-contexts",
        passed=bool(text) and not missing and not invalid_job_env,
        detail=(
            "foundation workflow has valid triggers, Node 24 actions, and Linux temp root"
            if text and not missing and not invalid_job_env
            else f"missing={missing}; invalid_runner_context={invalid_job_env}"
        ),
    )


def _fallback_wired() -> AuditCheck:
    init = _read("research_engine/__init__.py")
    synth = _read("research_engine/synthesizer.py")
    orchestrator = _read("research_engine/orchestrator.py")
    status = _read("utils/reasoning_status.py")
    missing: List[str] = []
    expectations = (
        (init, "reasoning_router_integrated", "package resilient-router facade"),
        (synth, "OfflineEvidenceReasoner", "deterministic evidence fallback"),
        (synth, "PresentationGuard", "presentation guard"),
        (orchestrator, "extractive_summary(question, pack)", "orchestrator no-model fallback"),
        (status, "deterministic", "runtime fallback readiness"),
    )
    for text, needle, label in expectations:
        if needle not in text:
            missing.append(label)
    return AuditCheck(
        name="resilience:quota-does-not-blank-answer",
        passed=not missing,
        detail="provider + local/deterministic fallbacks wired" if not missing else "missing: " + ", ".join(missing),
    )


def _provider_cooldown_wired() -> AuditCheck:
    registry = _read("utils/provider_health.py")
    facade = _read("research_engine/reasoning_router_integrated.py")
    status = _read("utils/reasoning_status.py")
    env = _read(".env.example")
    required = [
        (registry, "class ProviderHealthRegistry", "provider health registry"),
        (registry, "record_failure", "failure recording"),
        (registry, "record_success", "success recovery"),
        (facade, "_HealthAwareProvider", "fallback-provider wrapper"),
        (facade, 'provider_health.blocked("gemini")', "Gemini cross-request skip"),
        (status, "temporarily_skipped", "public non-secret cooldown status"),
        (env, "PROVIDER_HEALTH_RATE_LIMIT_SECONDS", "cooldown configuration"),
    ]
    missing = [label for text, needle, label in required if needle not in text]
    return AuditCheck(
        name="resilience:cross-request-provider-cooldown",
        passed=not missing,
        detail=("known-dead providers are temporarily skipped across requests"
                if not missing else "missing: " + ", ".join(missing)),
    )


def _async_job_privacy() -> AuditCheck:
    routes = _read("api/job_routes.py")
    capability = _read("utils/job_access.py")
    required = [
        (routes, "X-Research-Job-Token", "private polling header"),
        (routes, "_authorized_job", "per-job authorization helper"),
        (routes, "job_access.verify", "capability verification"),
        (routes, "Depends(require_admin)", "server-wide listing admin guard"),
        (capability, "hmac.new", "HMAC capability token"),
        (capability, "secrets.token_bytes", "random server secret"),
        (capability, "research_job_capability.key", "durable local secret"),
        (capability, "ExclusiveProcessFileLock", "race-safe secret creation"),
        (capability, "compare_digest", "constant-time token comparison"),
    ]
    missing = [label for text, needle, label in required if needle not in text]
    return AuditCheck(
        name="security:async-job-capability",
        passed=not missing,
        detail=("job status/progress/result require an opaque capability"
                if not missing else "missing: " + ", ".join(missing)),
    )


def _project_isolation() -> AuditCheck:
    """Require project namespace auth all the way from server to shipped client."""
    main = _read("main.py")
    session = _read("api/session_routes.py")
    access = _read("utils/project_access.py")
    guard = _read("utils/project_guard.py")
    agent = _read("api/agent_routes.py")
    jobs = _read("api/job_routes.py")
    rag = _read("api/routes.py")
    exam = _read("api/exam_routes.py")
    reading = _read("api/reading_routes.py")
    web = _read("web/index.html")
    limiter = _read("utils/request_guard.py")

    required = [
        (main, "include_router(session_router", "session router mounted"),
        (main, '"X-Project-Token"', "project CORS/header contract"),
        (main, '"project_isolation": project_access.status()', "public readiness"),
        (session, "project_access.create()", "server-issued project session"),
        (session, "project_capability_tokens_ready", "session fail-closed readiness"),
        (access, "hmac.new", "HMAC project capability"),
        (access, "secrets.token_urlsafe", "random project namespace"),
        (access, "project_capability.key", "durable server-local project secret"),
        (access, "ExclusiveProcessFileLock", "race-safe project secret creation"),
        (guard, "project_access.verify", "project capability verification"),
        (guard, "status_code=404", "non-enumerating failure"),
        (agent, "require_project_access(request.project_id, x_project_token)", "chat/deep guard"),
        (jobs, "require_project_access(request.project_id, x_project_token)", "job-create guard"),
        (rag, "require_project_access(", "RAG/upload namespace guard"),
        (exam, "require_project_access(request.project_id, x_project_token)",
         "exam-analysis namespace guard"),
        (reading, "require_project_access(", "resumable-reading namespace guard"),
        (web, 'API+"/api/v1/session"', "web session creation"),
        (web, '"X-Project-Token":PROJECT.token', "web project bearer header"),
        (web, "async function projectPost", "web stale-session recovery wrapper"),
        (web, "attempt<2", "bounded one-refresh retry"),
        (limiter, '"/api/v1/session"', "session mint rate guard"),
        (limiter, "RATE_SESSION_PER_HOUR", "session rate configuration"),
    ]
    missing = [label for text, needle, label in required if needle not in text]
    return AuditCheck(
        name="security:project-namespace-capability",
        passed=not missing,
        detail=(
            "server-issued project capability guards public namespace access"
            if not missing else "missing: " + ", ".join(missing)
        ),
    )


def _storage_fail_closed() -> AuditCheck:
    paths = _read("utils/storage_paths.py")
    quota = _read("utils/storage_quota.py")
    jobs = _read("utils/research_jobs.py")
    process_lock = _read("utils/process_lock.py")
    archive = _read("utils/archive_manifest.py") + _read("utils/cloud_storage.py")
    required = [
        (paths, "INFINITY_DATA_ROOT", "central storage root"),
        (quota, "INFINITY_MIN_FREE_GB", "minimum free-space guard"),
        (jobs, "RESEARCH_JOB_RESULT_MAX_MB", "job result cap"),
        (process_lock, "process", "single-writer/process lock"),
        (archive, "verified", "verified cloud lifecycle"),
    ]
    missing = [label for text, needle, label in required if needle not in text]
    return AuditCheck(
        name="storage:bounded-and-verified",
        passed=not missing,
        detail="bounded durable storage invariants present" if not missing else "missing: " + ", ".join(missing),
    )


def _obvious_secret_scan() -> AuditCheck:
    """Catch obvious real credential literals in production files.

    This is intentionally conservative and excludes tests/docs/examples so fake
    fixtures such as `gsk_test` do not make the release gate noisy. It is not a
    full secret scanner and never claims to be one.
    """
    production_roots = [ROOT / "research_engine", ROOT / "api", ROOT / "utils", ROOT / "storage"]
    files: List[Path] = [ROOT / "main.py"]
    for base in production_roots:
        if base.is_dir():
            files.extend(path for path in base.rglob("*.py") if path.is_file())

    patterns = {
        "google-like": re.compile(r"AIza[0-9A-Za-z_-]{25,}"),
        "openai-like": re.compile(r"sk-[0-9A-Za-z_-]{20,}"),
        "groq-like": re.compile(r"gsk_[0-9A-Za-z_-]{20,}"),
        "openrouter-like": re.compile(r"sk-or-v1-[0-9A-Za-z]{20,}"),
    }
    hits: List[str] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for name, pattern in patterns.items():
            if pattern.search(text):
                hits.append(f"{path.relative_to(ROOT).as_posix()}:{name}")
    return AuditCheck(
        name="security:no-obvious-credential-literals",
        passed=not hits,
        detail="no obvious credential literal found" if not hits else "hits: " + ", ".join(hits[:10]),
    )


def run_audit() -> AuditReport:
    required = (
        "main.py",
        "api/job_routes.py",
        "api/session_routes.py",
        "api/exam_routes.py",
        "api/reading_routes.py",
        "research_engine/orchestrator.py",
        "research_engine/source_discovery.py",
        "research_engine/content_fetcher.py",
        "research_engine/network_safety.py",
        "research_engine/evidence.py",
        "research_engine/claim_verification.py",
        "research_engine/locator_policy.py",
        "research_engine/contradiction.py",
        "research_engine/gemini_reasoning.py",
        "research_engine/reasoning_router.py",
        "research_engine/reasoning_router_integrated.py",
        "research_engine/offline_reasoner.py",
        "research_engine/hypothesis.py",
        "research_engine/advanced_discovery.py",
        "research_engine/specialist_domains.py",
        "research_engine/multilingual_research.py",
        "research_engine/exam_intelligence.py",
        "docs/EXAM_INTELLIGENCE.md",
        "research_engine/reading_sessions.py",
        "docs/RESUMABLE_READING.md",
        "docs/EVIDENCE_MUTATION_MATRIX.md",
        "research_engine/patents.py",
        "research_engine/connectors/patent_connector.py",
        "scripts/run_live_zero_cost_gate.py",
        "scripts/run_offline_api_smoke.py",
        "RUN_LIVE_ZERO_COST_GATE.ps1",
        "START_BACKEND.bat",
        "research_engine/verification.py",
        "research_engine/synthesizer.py",
        "research_engine/presentation_guard.py",
        "utils/zero_cost_guard.py",
        "utils/provider_health.py",
        "utils/job_access.py",
        "utils/project_access.py",
        "utils/project_guard.py",
        "utils/request_guard.py",
        "utils/research_jobs.py",
        "utils/storage_paths.py",
        "utils/storage_quota.py",
        "web/index.html",
        "tests/test_relevance_domain.py",
        "tests/test_claim_verification.py",
        "tests/test_reasoning_router_integration.py",
        "tests/test_provider_health.py",
        "tests/test_job_access.py",
        "tests/test_job_routes_access.py",
        "tests/test_job_result_progress_snapshot.py",
        "tests/test_project_access.py",
        "tests/test_project_route_guards.py",
        "tests/test_project_wiring.py",
        "tests/test_web_job_capability.py",
        "tests/test_offline_reasoner.py",
        "tests/test_release_state.py",
        "tests/test_network_safety.py",
        "tests/test_unverified_semantics.py",
        "tests/test_advanced_discovery.py",
        "tests/test_specialist_research.py",
        "tests/test_exam_intelligence.py",
        "tests/test_resumable_reading.py",
        "tests/test_evidence_mutation_matrix.py",
        "tests/test_patents.py",
        "tests/test_chat_resilience.py",
        "tests/test_live_zero_cost_gate.py",
        "tests/test_windows_launchers.py",
        "tests/benchmark_cross_domain.py",
        "tests/benchmark_superconductivity.py",
    )

    checks = [
        _required_files(required),
        _contains(
            "main.py",
            "enforce_zero_cost_config()",
            "protect_free_quota",
            "include_router",
            "reasoning_status",
            "include_router(exam_router",
            "include_router(reading_router",
        ),
        _release_honesty(),
        _contains(
            "research_engine/orchestrator.py",
            "self._discover(",
            "self._run_passes(",
            "verify_claims(",
            "label_report=label_report",
            "claim_checks=claim_checks",
            "self.citations.verify(",
            "self.verifier.verify(",
            "self.scientific_discovery.analyze(",
            "self.synthesizer.assemble(",
        ),
        _contains(
            "research_engine/advanced_discovery.py",
            "class ScientificDiscoveryEngine",
            "class SafeNumericExecutor",
            '"arbitrary_python": False',
            '"global_novelty_claimed": False',
            '"real_world_success_probability_claimed": False',
            '"max_inferred_without_experiment": 3',
        ),
        _contains(
            "research_engine/specialist_domains.py",
            "class SpecialistProfile",
            '"official_document_record"',
            '"traditional_belief_text"',
            '"allegation_or_conspiracy_claim"',
            '"app_original_hypothesis"',
            '"truth_probability_claim_allowed": False',
            "def build_evidence_lane_report(",
        ),
        _contains(
            "research_engine/multilingual_research.py",
            "def build_multilingual_plan(",
            '"original_preserved": True',
            '"paywall_or_copyright_bypass": False',
            "Glossary-assisted search is not full-text translation",
        ),
        _contains(
            "research_engine/exam_intelligence.py",
            "class ExamIntelligenceEngine",
            "expanding-window temporal holdout",
            "CALIBRATED_ON_WALK_FORWARD_HISTORY",
            "APP-ORIGINAL EXAM HYPOTHESIS",
            "HEURISTIC STUDY PRIORITY — NOT PROBABILITY",
            "ExclusiveProcessFileLock",
        ),
        _contains(
            "research_engine/reading_sessions.py",
            "class ReadingSessionStore",
            "class ResumableReadingManager",
            "pending_semantic_translation_review",
            "text_extraction_is_not_comprehension",
            "password_drm_paywall_bypass",
            "ExclusiveProcessFileLock",
        ),
        _contains(
            "research_engine/locator_policy.py",
            "def exact_locator_available(",
            "exact page ka pata nahi",
            "abstract/snippet",
        ),
        _contains(
            "research_engine/dedup.py",
            "normalize_doi",
            "merge_exact_duplicate",
            "sabse gehra available",
            "doi_key != twin_doi",
        ),
        _contains(
            "research_engine/planner.py",
            "build_specialist_plan(",
            "specialist_queries(",
            '"official_archive_queries"',
            '"book_queries"',
        ),
        _contains(
            "research_engine/source_discovery.py",
            'plan.get("official_archive_queries", [])',
            'plan.get("book_queries", [])',
            '"official_archive_web"',
        ),
        _contains(
            "research_engine/orchestrator.py",
            "build_evidence_lane_report(",
            "specialist_report=specialist_report",
            "specialist_research=specialist_report",
        ),
        _contains(
            "research_engine/depth.py",
            "MARATHON = DepthConfig(",
            'name="MARATHON"',
            '"MARATHON": MARATHON',
        ),
        _contains(
            "api/job_routes.py",
            '"MARATHON"',
        ),
        _contains(
            "web/index.html",
            'data-mode="MARATHON"',
            'requestedMode==="MARATHON"',
        ),
        _contains(
            "research_engine/planner.py",
            "patent_intent(",
            '"patents": patents',
            'getattr(config, "use_patents"',
        ),
        _contains(
            "research_engine/orchestrator.py",
            "self._patent_prior_art(",
            "novelty_overclaim(",
            'coverage["prior_art"]',
        ),
        _contains(
            "api/agent_routes.py",
            "use_patents: Optional[bool]",
        ),
        _contains(
            "api/job_routes.py",
            "use_patents: Optional[bool]",
        ),
        _contains(
            "scripts/run_live_zero_cost_gate.py",
            "def preflight(",
            "def _validate_runtime_storage(",
            "inspect_zero_cost_config",
            "has_model_layer_usable_now",
            "def evaluate_result(",
            "live_research_execution_failed",
            '"--data-root"',
            '"contains_credentials": False',
        ),
        _contains(
            "RUN_LIVE_ZERO_COST_GATE.ps1",
            "$PSScriptRoot",
            '"--data-root"',
            "$gateExitCode",
        ),
        _contains(
            "START_BACKEND.bat",
            'cd /d "%~dp0"',
            "venv\\Scripts\\python.exe",
            "--host 127.0.0.1 --port 8000",
        ),
        _contains(
            "scripts/run_offline_api_smoke.py",
            "TemporaryDirectory",
            '"GEMINI_API_KEY": ""',
            '"GROQ_API_KEY": ""',
            '"OPENROUTER_API_KEY": ""',
            '"OLLAMA_ENABLED": "false"',
            'client.post("/api/v1/session")',
            'client.post("/api/v1/chat"',
            'client.post("/api/v1/research-jobs"',
            '"unsupported VERIFIED claim is blocked"',
        ),
        _contains(
            "research_engine/content_fetcher.py",
            "safe_get_with_redirects(",
            "resolve_dns=True",
            "require_content_type(resp, kind)",
            "declared_length(resp)",
        ),
        _contains(
            "research_engine/connectors/base.py",
            "DISCOVERY_ALLOWED_HOSTS",
            "read_bounded_response(",
            "allowed_hosts=DISCOVERY_ALLOWED_HOSTS",
            "public_error(exc)",
        ),
        _contains(
            "research_engine/models.py",
            "UNVERIFIED = \"UNVERIFIED\"",
            '"UNVERIFIED": ClaimType.UNVERIFIED',
            'payload["claim_state"]',
        ),
        _ordered(
            "research_engine/orchestrator.py",
            (
                ("discover", "self._discover("),
                ("reason", "self._run_passes("),
                ("claim-check", "verify_claims("),
                ("citation-check", "self.citations.verify("),
                ("verification", "self.verifier.verify("),
                ("synthesis", "self.synthesizer.assemble("),
            ),
        ),
        _zero_cost_chain(),
        _fallback_wired(),
        _provider_cooldown_wired(),
        _project_isolation(),
        _async_job_privacy(),
        _contains(
            "api/job_routes.py",
            "def _progress_result_snapshot(",
            'response["research_progress"]',
            "_PROGRESS_LOG_LIMIT",
            "_UNSAFE_PROGRESS_MARKERS",
        ),
        _storage_fail_closed(),
        _no_wildcard_cors(),
        _obvious_secret_scan(),
        _foundation_workflow_safe(),
        _contains(
            "scripts/run_foundation_gate.py",
            "architecture_audit",
            "benchmark_cross_domain",
            "benchmark_superconductivity_v2",
            "test_network_safety.py",
            "test_unverified_semantics.py",
            "test_advanced_discovery.py",
            "test_specialist_research.py",
            "run_offline_api_smoke.py",
            "test_patents.py",
            "test_chat_resilience.py",
            "test_live_zero_cost_gate.py",
            "test_reasoning_router_integration.py",
            "test_provider_health.py",
            "test_job_access.py",
            "test_job_result_progress_snapshot.py",
            "test_project_access.py",
            "test_project_route_guards.py",
            "test_project_wiring.py",
            "test_offline_reasoner.py",
            "test_release_state.py",
        ),
    ]
    failed = [check.name for check in checks if not check.passed]
    return AuditReport(
        schema_version=1,
        passed=not failed,
        checks=[asdict(check) for check in checks],
        failed=failed,
    )


def _write_json(path: Path, report: AuditReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit production research-engine wiring and safety invariants.")
    parser.add_argument("--json", dest="json_path", help="Optional JSON report path.")
    args = parser.parse_args(argv)

    report = run_audit()
    for row in report.checks:
        marker = "PASS" if row["passed"] else "FAIL"
        print(f"[{marker}] {row['name']}: {row['detail']}")
    if args.json_path:
        _write_json(Path(args.json_path).expanduser().resolve(), report)
        print(f"Architecture audit JSON: {Path(args.json_path).expanduser().resolve()}")
    print("ARCHITECTURE AUDIT: " + ("PASS" if report.passed else "FAIL"))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
