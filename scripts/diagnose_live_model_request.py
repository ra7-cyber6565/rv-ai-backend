"""One-call, public-safe diagnostic for the configured Gemini reasoning model.

This script exists because a full live research gate is expensive in free-tier
quota and its public receipt intentionally hides provider bodies. It performs
exactly one synthetic generation request against GEMINI_MODEL, never rotates to
another model/key, never retries, and emits only coarse metadata:

- configured model name and prompt character count;
- whether a provider response arrived;
- whether usable text existed and its length;
- normalized failure kind / exception class / finish reason.

It never emits credentials, prompt text, response text, raw exception messages,
source content or URLs. When ``--receipt`` is supplied, the exact same sanitized
report is atomically persisted so a failed auth/model preflight still leaves a
machine-readable acceptance artifact.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_local_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
    except Exception:
        return


def build_prompt(target_chars: int = 50000) -> str:
    """Deterministic inert evidence prompt with preserved source boundaries."""
    target = max(4000, min(int(target_chars), 120000))
    prefix = (
        "Reply only OK. This is inert request-size diagnostic evidence.\n"
        "BEGIN_UNTRUSTED_SOURCES\n"
        "[D1] SOURCE DESCRIPTOR (quoted data):\n"
        "DATA> Synthetic diagnostic record; not a factual source.\n"
    )
    suffix = "\nEND_UNTRUSTED_SOURCES\n"
    line = "DATA> superconductivity evidence record for request-size diagnostic only.\n"
    body_budget = max(0, target - len(prefix) - len(suffix))
    repeats = (body_budget // len(line)) + 1
    body = (line * repeats)[:body_budget]
    return prefix + body + suffix


def _finish_reasons(response: Any) -> list[str]:
    rows: list[str] = []
    for candidate in list(getattr(response, "candidates", []) or []):
        reason = getattr(candidate, "finish_reason", "")
        value = str(getattr(reason, "name", "") or reason or "").strip()
        if value and value not in rows:
            rows.append(value[:64])
    return rows[:4]


def inspect_response(response: Any) -> Dict[str, Any]:
    """Return only safe response metadata; response text itself is discarded."""
    from research_engine.model_errors import classify

    out: Dict[str, Any] = {"response_received": True}
    try:
        text = str(getattr(response, "text", "") or "").strip()
        out["text_ok"] = bool(text)
        out["text_chars"] = len(text)
    except Exception as exc:  # noqa: BLE001 - normalized below, raw body hidden
        out["text_ok"] = False
        out["text_error_kind"] = classify(exc).kind
        out["text_exception_class"] = type(exc).__name__[:64]
        out["finish_reasons"] = _finish_reasons(response)
    return out


def diagnose_request(
    model_name: str,
    *,
    prompt_chars: int = 50000,
    model_factory: Optional[Callable[[str], Any]] = None,
    generate_fn: Optional[Callable[[Any, str], Any]] = None,
) -> Dict[str, Any]:
    """Perform exactly one generation attempt with no retry or model fallback."""
    from research_engine.model_errors import classify

    prompt = build_prompt(prompt_chars)
    out: Dict[str, Any] = {
        "configured_model": str(model_name or ""),
        "prompt_chars": len(prompt),
        "generation_calls": 1,
        "retry_calls": 0,
        "fallback_calls": 0,
    }
    try:
        if model_factory is None:
            import google.generativeai as genai
            model_factory = genai.GenerativeModel
        if generate_fn is None:
            from research_engine.gemini_model import generate
            generate_fn = generate
        model = model_factory(model_name)
        response = generate_fn(model, prompt)
        out.update(inspect_response(response))
    except Exception as exc:  # noqa: BLE001 - never expose provider body
        out["response_received"] = False
        out["request_error_kind"] = classify(exc).kind
        out["request_exception_class"] = type(exc).__name__[:64]
    return out


def _public_report(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize receipt invariants without copying any private provider data."""
    out = dict(payload)
    out["contains_prompt_or_response_text"] = False
    out["contains_credentials"] = False
    return out


def _write_receipt(path: Path, payload: Mapping[str, Any]) -> None:
    """Atomically persist the already-sanitized diagnostic receipt."""
    path.parent.mkdir(parents=True, exist_ok=True)
    safe = _public_report(payload)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(safe, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _emit(
    payload: Mapping[str, Any],
    *,
    exit_code: int,
    receipt: Optional[Path],
) -> int:
    safe = _public_report(payload)
    if receipt is not None:
        _write_receipt(receipt, safe)
    print(json.dumps(safe, ensure_ascii=False, indent=2))
    return int(exit_code)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Exactly one safe Gemini request diagnostic; no retry/fallback."
    )
    parser.add_argument("--prompt-chars", type=int, default=50000)
    parser.add_argument(
        "--receipt",
        help="optional sanitized JSON receipt path; written even on safe failure",
    )
    args = parser.parse_args(argv)
    receipt = Path(args.receipt).resolve() if args.receipt else None

    load_local_env()
    from utils.zero_cost_guard import inspect_zero_cost_config
    from research_engine.key_pool import KeyPool
    from research_engine.gemini_model import configure

    zero = inspect_zero_cost_config(os.environ)
    model_name = str(os.getenv("GEMINI_MODEL", "") or "").strip()
    pool = KeyPool()
    if not zero.enabled:
        return _emit(
            {
                "ready": False,
                "passed": False,
                "generation_calls": 0,
                "blocker": "ZERO_COST_ONLY must be true",
            },
            exit_code=2,
            receipt=receipt,
        )
    if zero.blocked_keys:
        return _emit(
            {
                "ready": False,
                "passed": False,
                "generation_calls": 0,
                "blocker": "zero-cost confirmation/configuration is incomplete",
            },
            exit_code=2,
            receipt=receipt,
        )
    if not pool.has_key() or not model_name:
        return _emit(
            {
                "ready": False,
                "passed": False,
                "generation_calls": 0,
                "blocker": "Gemini key or GEMINI_MODEL is missing",
            },
            exit_code=2,
            receipt=receipt,
        )

    import google.generativeai as genai
    configure(genai, pool.active())
    out: Dict[str, Any] = {
        "ready": True,
        "active_key": pool.label(),
    }
    out.update(diagnose_request(model_name, prompt_chars=args.prompt_chars))
    passed = bool(out.get("response_received") and out.get("text_ok"))
    out["passed"] = passed
    return _emit(out, exit_code=0 if passed else 1, receipt=receipt)


if __name__ == "__main__":
    raise SystemExit(main())
