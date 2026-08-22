"""Run the credential-gated live ₹0 research release check.

Default behaviour is preflight-only.  A real provider/search run happens only
with ``--execute`` and only after the configured model layer passes the hard
zero-cost guard.  The receipt intentionally excludes prompts, answers, source
text/URLs and credentials; it stores only non-secret counts and an answer hash.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LIVE_QUESTION = (
    "Kya room-temperature superconductivity practically possible hai? Ambient "
    "pressure par hydrides aur cuprates ke confirmed limits compare karo, "
    "replication/retraction evidence check karo, power-grid aur quantum-computing "
    "impact samjhao, aur evidence allow kare to 3 testable hypotheses unke "
    "falsification experiments ke saath do."
)
RAW_PUBLIC_TOKENS = (
    "resourceexhausted", "grpc_status", "quota_id", "retry_delay",
    "traceback", "protobuf", "permissiondenied", "invalidargument",
    "generaterequestsperday", "<class", "api_key=",
)


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def load_local_env() -> None:
    """Load a private .env when python-dotenv is installed; never print it."""
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
    except Exception:
        return


def preflight(env: Mapping[str, str]) -> Dict[str, Any]:
    from utils.reasoning_status import reasoning_status
    from utils.zero_cost_guard import inspect_zero_cost_config

    zero = inspect_zero_cost_config(env)
    reasoning = reasoning_status(env)
    blockers = []
    if not zero.enabled:
        blockers.append("ZERO_COST_ONLY must be true")
    blockers.extend(str(item) for item in zero.blocked_keys)
    if not str(env.get("INFINITY_DATA_ROOT", "") or "").strip():
        blockers.append("INFINITY_DATA_ROOT must be explicit")
    if not reasoning.get("has_model_layer_usable_now"):
        blockers.append("no confirmed/free model layer is usable now")
    return {
        "ready": not blockers,
        "zero_cost_only": bool(zero.enabled),
        "model_layers_configured": int(reasoning.get("model_layers_configured") or 0),
        "model_layers_usable_now": int(reasoning.get("model_layers_usable_now") or 0),
        "has_model_backup": bool(reasoning.get("has_model_backup")),
        "blockers": blockers,
        "credentials_exposed": False,
    }


def evaluate_result(result: Mapping[str, Any]) -> Dict[str, Any]:
    coverage = result.get("coverage") or {}
    verification = result.get("verification") or {}
    claim_checks = verification.get("claim_checks") or {}
    discovery = result.get("discovery") or {}
    answer = str(result.get("answer") or "")
    warnings = " ".join(str(item) for item in (result.get("warnings") or []))
    public = (answer + " " + warnings).lower()
    sources = result.get("sources") or []
    hypotheses = result.get("hypotheses") or []
    evidence_level = str(result.get("evidence_level") or "")

    checks = [
        ("status_complete", result.get("status") == "COMPLETE",
         str(result.get("status") or "missing")),
        ("sources_retrieved", len(sources) >= 3, f"{len(sources)} source(s)"),
        ("on_topic_sources", int(coverage.get("on_topic_sources") or 0) >= 3,
         f"{int(coverage.get('on_topic_sources') or 0)} on-topic"),
        ("full_text_read", int(coverage.get("full_text_sources_read") or 0) >= 1,
         f"{int(coverage.get('full_text_sources_read') or 0)} full-text"),
        ("valid_citations", not (result.get("invalid_citations") or []),
         f"{len(result.get('invalid_citations') or [])} invalid"),
        ("citations_present", len(result.get("citations") or []) >= 1,
         f"{len(result.get('citations') or [])} citation(s)"),
        ("claim_gate", claim_checks.get("gate_passed") is not False,
         str(claim_checks.get("gate_passed"))),
        ("three_hypotheses", len(hypotheses) >= 3,
         f"{len(hypotheses)} hypothesis/hypotheses"),
        ("advanced_discovery", discovery.get("status") == "ASSESSMENT_READY",
         str(discovery.get("status") or "missing")),
        ("tournament_ready", bool((discovery.get("tournament") or {}).get("winner")),
         str((discovery.get("tournament") or {}).get("winner") or "missing")),
        ("honest_evidence_label",
         "INCOMPLETE" not in evidence_level.upper() and "UNVERIFIED" not in evidence_level.upper(),
         evidence_level[:160]),
        ("no_raw_provider_error", not any(token in public for token in RAW_PUBLIC_TOKENS),
         "public answer/warnings sanitized"),
        ("no_global_novelty_claim", discovery.get("global_novelty_claimed") is False,
         str(discovery.get("global_novelty_claimed"))),
        ("no_success_probability_claim",
         discovery.get("real_world_success_probability_claimed") is False,
         str(discovery.get("real_world_success_probability_claimed"))),
        ("human_review_required", discovery.get("human_review_required") is True,
         str(discovery.get("human_review_required"))),
    ]
    rows = [{"name": name, "passed": bool(passed), "detail": detail}
            for name, passed, detail in checks]
    return {
        "passed": all(row["passed"] for row in rows),
        "checks": rows,
        "summary": {
            "status": str(result.get("status") or ""),
            "sources": len(sources),
            "on_topic_sources": int(coverage.get("on_topic_sources") or 0),
            "full_text_sources_read": int(coverage.get("full_text_sources_read") or 0),
            "citations": len(result.get("citations") or []),
            "hypotheses": len(hypotheses),
            "discovery_status": str(discovery.get("status") or ""),
            "answer_sha256": hashlib.sha256(answer.encode("utf-8")).hexdigest(),
        },
    }


def _receipt_path(value: str | None, env: Mapping[str, str]) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    root = Path(str(env["INFINITY_DATA_ROOT"])).expanduser().resolve()
    return root / "audit" / "live_zero_cost_gate_latest.json"


def _write_receipt(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def run_live() -> Dict[str, Any]:
    from research_engine.orchestrator import DeepResearchEngine

    project = f"live_gate_{int(time.time())}"
    engine = DeepResearchEngine(project_id=project, enable_kg=False, enable_memory=False)
    return engine.research(LIVE_QUESTION, depth_mode="MAXIMUM", job_id=project)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preflight or execute the confirmed ₹0 live research gate.")
    parser.add_argument("--execute", action="store_true",
                        help="After safe preflight, perform the real live research run.")
    parser.add_argument("--receipt", help="Non-secret JSON receipt path.")
    args = parser.parse_args(argv)

    load_local_env()
    ready = preflight(os.environ)
    print("LIVE ₹0 PREFLIGHT: " + ("READY" if ready["ready"] else "BLOCKED"))
    for blocker in ready["blockers"]:
        print(f"- {blocker}")
    print(f"Model layers usable now: {ready['model_layers_usable_now']}")
    if not ready["ready"]:
        return 2
    if not args.execute:
        print("No live call made. Add --execute when final live testing is intended.")
        return 0

    started = time.time()
    result = run_live()
    evaluation = evaluate_result(result)
    receipt = {
        "schema_version": 1,
        "created_at_epoch": int(time.time()),
        "duration_seconds": round(time.time() - started, 2),
        "zero_cost_preflight": ready,
        "passed": evaluation["passed"],
        "checks": evaluation["checks"],
        "summary": evaluation["summary"],
        "contains_answer_or_source_text": False,
        "contains_credentials": False,
    }
    path = _receipt_path(args.receipt, os.environ)
    _write_receipt(path, receipt)
    for row in evaluation["checks"]:
        print(f"[{'PASS' if row['passed'] else 'FAIL'}] {row['name']}: {row['detail']}")
    print("LIVE ZERO-COST GATE: " + ("PASS" if evaluation["passed"] else "FAIL"))
    print(f"Receipt: {path}")
    return 0 if evaluation["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
