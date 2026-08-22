"""One-call, public-safe diagnostic for the configured Gemini reasoning model.

This script exists because a full live research gate is expensive in free-tier
quota and its public receipt intentionally hides provider bodies. It performs
exactly one synthetic generation request against GEMINI_MODEL, never rotates to
another model/key, never retries, and prints only coarse metadata:

- configured model name and prompt character count;
- whether a provider response arrived;
- whether usable text existed and its length;
- normalized failure kind / exception class / finish reason.

It never prints credentials, prompt text, response text, raw exception messages,
source content or URLs.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional


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


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Exactly one safe Gemini request diagnostic; no retry/fallback."
    )
    parser.add_argument("--prompt-chars", type=int, default=50000)
    args = parser.parse_args(argv)

    load_local_env()
    from utils.zero_cost_guard import inspect_zero_cost_config
    from research_engine.key_pool import KeyPool
    from research_engine.gemini_model import configure

    zero = inspect_zero_cost_config(os.environ)
    model_name = str(os.getenv("GEMINI_MODEL", "") or "").strip()
    pool = KeyPool()
    if not zero.enabled:
        print(json.dumps({
            "ready": False,
            "generation_calls": 0,
            "blocker": "ZERO_COST_ONLY must be true",
        }, indent=2))
        return 2
    if zero.blocked_keys:
        print(json.dumps({
            "ready": False,
            "generation_calls": 0,
            "blocker": "zero-cost confirmation/configuration is incomplete",
        }, indent=2))
        return 2
    if not pool.has_key() or not model_name:
        print(json.dumps({
            "ready": False,
            "generation_calls": 0,
            "blocker": "Gemini key or GEMINI_MODEL is missing",
        }, indent=2))
        return 2

    import google.generativeai as genai
    configure(genai, pool.active())
    out = {"ready": True, "active_key": pool.label()}
    out.update(diagnose_request(model_name, prompt_chars=args.prompt_chars))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("response_received") and out.get("text_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
