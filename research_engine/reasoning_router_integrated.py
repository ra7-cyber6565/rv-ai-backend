"""Integration facade for the quota-resilient reasoning router.

Claude's latest GeminiReasoning now records pass-level accounting (`pass_log`,
`same_model_retries`, honest model switches).  The provider fallback router was
written before those fields landed.  This tiny facade keeps both systems intact:

- one logical research pass stays one budget unit even if provider fallback runs;
- a Gemini-failed/OpenRouter-success pass is recorded as OUTPUT, not empty;
- HTTP attempts include primary + provider fallbacks;
- same-model retries stay separate from model/provider switches;
- the synthesizer receives the complete §14 accounting schema.
"""
from __future__ import annotations

from typing import Dict, Iterable, Optional

from .reasoning_router import (
    ProviderResult,
    QuotaExhausted,
    ReasoningProvider,
    ResilientReasoning as _Router,
)


class ResilientReasoning(_Router):
    """Latest Gemini accounting + provider-level ₹0 failover."""

    def __init__(self, *args, fallback_providers: Optional[Iterable[ReasoningProvider]] = None,
                 **kwargs):
        super().__init__(*args, fallback_providers=fallback_providers, **kwargs)

    def generate(self, prompt: str, label: str = "") -> str:
        before_log = len(getattr(self, "pass_log", []))
        attempts_before = int(getattr(self, "attempts", 0) or 0)
        text = super().generate(prompt, label)
        attempts_delta = max(0, int(getattr(self, "attempts", 0) or 0) - attempts_before)
        log = getattr(self, "pass_log", None)
        if log is None:
            return text

        tag = label or "reasoning"
        if len(log) == before_log:
            # Primary Gemini was intentionally skipped (missing/blocked key), so
            # Claude's wrapper never got a chance to append a pass record.
            model = ""
            if text and getattr(self, "models_tried", None):
                model = str(self.models_tried[-1])
            log.append({
                "label": tag,
                "ok": bool(text),
                "http_attempts": attempts_delta,
                "model": model,
            })
        else:
            # Gemini may have appended `ok=False` before a later provider saved
            # the SAME logical pass. Rewrite that record to describe the final
            # pass outcome and total HTTP attempts, not the failed first provider.
            row = log[-1]
            if isinstance(row, dict):
                row["label"] = tag
                row["ok"] = bool(text)
                row["http_attempts"] = attempts_delta
                if text and getattr(self, "provider_switches", 0):
                    if getattr(self, "models_tried", None):
                        row["model"] = str(self.models_tried[-1])
        return text

    def usage_note(self) -> str:
        if not self.router_active:
            return super().usage_note()
        asked = len(getattr(self, "pass_log", []) or [])
        got = sum(1 for row in (getattr(self, "pass_log", []) or [])
                  if isinstance(row, dict) and row.get("ok"))
        bits = [f"{self.calls_used}/{self.budget} reasoning pass maange gaye"]
        if asked:
            bits.append(f"inmein se {got}/{asked} se sach mein output aaya")
        bits.append(f"{self.attempts} total provider/API attempts")
        if getattr(self, "same_model_retries", 0):
            bits.append(f"{self.same_model_retries} same-model retry")
        total_switches = int(getattr(self, "switched_models", 0) or 0) + int(
            getattr(self, "provider_switches", 0) or 0
        )
        if total_switches:
            bits.append(f"{total_switches} model/provider fallback")
        if self.provider_switches:
            bits.append(f"{self.provider_switches} pass backup provider par complete")
        return ", ".join(bits)

    def api_accounting(self) -> Dict:
        if not self.router_active:
            return super().api_accounting()

        base = dict(super().api_accounting())
        log = [dict(row) for row in (getattr(self, "pass_log", []) or [])
               if isinstance(row, dict)]
        asked = len(log)
        got = sum(1 for row in log if row.get("ok"))
        empty = [str(row.get("label") or "reasoning") for row in log if not row.get("ok")]
        attempts = int(getattr(self, "attempts", 0) or 0)
        successes = int(getattr(self, "successes", 0) or 0)
        total_switches = int(getattr(self, "switched_models", 0) or 0) + int(
            getattr(self, "provider_switches", 0) or 0
        )

        blocked_models = dict(getattr(self, "blocked", {}) or {})
        for provider, kind in (getattr(self, "blocked_providers", {}) or {}).items():
            blocked_models[f"provider:{provider}"] = kind

        base.update({
            "logical_reasoning_calls": int(getattr(self, "calls_used", 0) or 0),
            "budget": int(getattr(self, "budget", 0) or 0),
            "passes_requested": asked,
            "passes_with_output": got,
            "passes_empty": max(0, asked - got),
            "empty_output_passes": empty,
            "pass_log": log,
            "actual_http_attempts": attempts,
            "successful_calls": successes,
            "failed_http_attempts": max(0, attempts - successes),
            "failed_attempts": max(0, attempts - successes),
            "same_model_retries": int(getattr(self, "same_model_retries", 0) or 0),
            "retries": int(getattr(self, "same_model_retries", 0) or 0),
            "model_switches": total_switches,
            "provider_fallbacks": int(getattr(self, "provider_switches", 0) or 0),
            "provider_attempts": dict(getattr(self, "provider_attempts", {}) or {}),
            "provider_successes": dict(getattr(self, "provider_successes", {}) or {}),
            "provider_failures": dict(getattr(self, "provider_failures", {}) or {}),
            "models_tried": list(getattr(self, "models_tried", []) or []),
            "blocked_models": blocked_models,
            "blocked_providers": dict(getattr(self, "blocked_providers", {}) or {}),
            "failure_summary": self.failure_reason(),
            "stopped_early": bool(self.failure_kind() and not getattr(self, "_router_last_success", False)),
            "no_api_calls": attempts == 0,
            "counted_by": "engine ki apni ginti (provider billing dashboard se nahi)",
        })
        return base


__all__ = ["ResilientReasoning", "ProviderResult", "ReasoningProvider", "QuotaExhausted"]
