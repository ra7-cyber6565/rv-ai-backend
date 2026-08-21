"""Integration facade for the quota-resilient reasoning router.

Claude's GeminiReasoning records pass-level accounting and can rotate across
configured Gemini keys. The provider router adds Groq/OpenRouter/Ollama fallback.
This facade keeps those two layers consistent and enforces public-safe accounting:

- one logical research pass stays one budget unit even if fallback runs;
- a failed-primary/successful-backup pass is recorded as OUTPUT, not empty;
- HTTP attempts include primary + provider fallbacks;
- same-model retries stay separate from model/provider/key switches;
- backup-only Gemini configuration is recognized under the same ₹0 confirmation;
- raw SDK/HTTP/protobuf bodies are never returned by errors/technical_details;
- hard quota/auth/provider outages are remembered briefly across requests so a
  known-dead free provider is not hit again by every new chat/research request.
"""
from __future__ import annotations

import os
from typing import Dict, Iterable, List, Optional

from utils.provider_health import provider_health
from utils.zero_cost_guard import gemini_credentials_configured, zero_cost_enabled

from .reasoning_router import (
    ProviderResult,
    QuotaExhausted,
    ReasoningProvider,
    ResilientReasoning as _Router,
)


_TRUTHY = {"1", "true", "yes", "on"}


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in _TRUTHY


class _HealthAwareProvider(ReasoningProvider):
    """Delegate provider calls through the process-local cooldown registry."""

    def __init__(self, provider: ReasoningProvider):
        self._provider = provider
        self.name = str(getattr(provider, "name", "provider") or "provider")
        self.model = str(getattr(provider, "model", "") or "")

    @property
    def configured(self) -> bool:
        return bool(getattr(self._provider, "configured", True))

    def generate(self, prompt: str, label: str = "") -> ProviderResult:
        blocked, reason, remaining = provider_health.blocked(self.name)
        if blocked:
            return ProviderResult(
                provider=self.name,
                model=self.model,
                attempts=0,
                kind="circuit_open",
                human=(
                    f"{self.name} ko recent {reason or 'availability'} failure ke baad "
                    f"{remaining}s ke liye skip kiya gaya."
                ),
                technical="",
                block_for_run=True,
            )

        result = self._provider.generate(prompt, label)
        if result.ok:
            provider_health.record_success(self.name)
        else:
            provider_health.record_failure(self.name, result.kind)
        return result


class ResilientReasoning(_Router):
    """Latest Gemini accounting + provider-level ₹0 failover."""

    def __init__(self, *args, fallback_providers: Optional[Iterable[ReasoningProvider]] = None,
                 **kwargs):
        super().__init__(*args, fallback_providers=fallback_providers, **kwargs)
        # Every hosted/local backup shares coarse cross-request health memory.
        # This adds no network call and stores no prompt/response/credential.
        self.fallback_providers = [
            provider if isinstance(provider, _HealthAwareProvider) else _HealthAwareProvider(provider)
            for provider in self.fallback_providers
        ]

    @staticmethod
    def _gemini_allowed() -> bool:
        """Primary OR backup Gemini credentials obey one zero-cost policy."""
        if not gemini_credentials_configured():
            return False
        if zero_cost_enabled() and not _truthy(os.getenv("GEMINI_ZERO_COST_CONFIRMED", "")):
            return False
        blocked, _, _ = provider_health.blocked("gemini")
        return not blocked

    def _redact_new_primary_errors(self, start: int, tag: str) -> None:
        """Replace raw provider exception strings with normalized failure kinds."""
        errors = getattr(self, "errors", None)
        if not isinstance(errors, list) or len(errors) <= start:
            return
        del errors[start:]
        kind = self.failure_kind() or "provider_unavailable"
        errors.append(f"{tag}: reasoning provider unavailable ({kind})")

    @staticmethod
    def _hardest_primary_failure(events: List[dict]) -> str:
        """Choose the most useful coarse Gemini cooldown reason."""
        kinds = [str(row.get("kind") or "").strip().lower() for row in events if isinstance(row, dict)]
        for wanted in ("auth", "permission", "daily_quota", "model_not_found", "rate_limit", "server", "network"):
            if wanted in kinds:
                return wanted
        return ""

    def generate(self, prompt: str, label: str = "") -> str:
        tag = label or "reasoning"
        before_log = len(getattr(self, "pass_log", []))
        attempts_before = int(getattr(self, "attempts", 0) or 0)
        errors_before = len(getattr(self, "errors", []) or [])
        events_before = len(getattr(getattr(self, "ledger", None), "events", []) or [])
        provider_switches_before = int(getattr(self, "provider_switches", 0) or 0)

        text = super().generate(prompt, label)

        events_after = list(getattr(getattr(self, "ledger", None), "events", []) or [])
        new_primary_events = [row for row in events_after[events_before:] if isinstance(row, dict)]
        provider_switches_after = int(getattr(self, "provider_switches", 0) or 0)
        fallback_saved_pass = provider_switches_after > provider_switches_before

        # Cross-request primary health memory is updated only after the complete
        # Gemini layer has either succeeded or really fallen through. Claude's
        # own Gemini key pool gets first chance to rotate across free keys.
        if text and not fallback_saved_pass:
            provider_health.record_success("gemini")
        elif fallback_saved_pass or not text:
            kind = self._hardest_primary_failure(new_primary_events)
            if kind:
                provider_health.record_failure("gemini", kind)

        # Even when no provider-level fallback is configured, the integrated
        # facade is the production class. Raw Gemini SDK exception strings must
        # therefore not survive in `errors`, because orchestrator can inspect it.
        if not text:
            self._redact_new_primary_errors(errors_before, tag)
        attempts_delta = max(0, int(getattr(self, "attempts", 0) or 0) - attempts_before)
        log = getattr(self, "pass_log", None)
        if log is None:
            return text

        if len(log) == before_log:
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
            row = log[-1]
            if isinstance(row, dict):
                row["label"] = tag
                row["ok"] = bool(text)
                row["http_attempts"] = attempts_delta
                if text and getattr(self, "provider_switches", 0):
                    if getattr(self, "models_tried", None):
                        row["model"] = str(self.models_tried[-1])
        return text

    def technical_details(self, limit: int = 8) -> List[str]:
        """Return coarse failure metadata only, never raw provider bodies."""
        rows: List[str] = []
        for event in list(getattr(getattr(self, "ledger", None), "events", []) or []):
            if not isinstance(event, dict):
                continue
            model = str(event.get("model") or "gemini")
            label = str(event.get("label") or "reasoning")
            kind = str(event.get("kind") or "unavailable")
            row = f"{model} / {label}: {kind}"
            if row not in rows:
                rows.append(row)
            if len(rows) >= limit:
                return rows
        for provider, kind in sorted((getattr(self, "blocked_providers", {}) or {}).items()):
            row = f"provider:{provider}: {kind or 'unavailable'}"
            if row not in rows:
                rows.append(row)
            if len(rows) >= limit:
                break
        return rows

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
        if getattr(self, "key_switches", 0):
            bits.append(f"{self.key_switches} Gemini backup-key switch")
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
        model_provider_switches = int(getattr(self, "switched_models", 0) or 0) + int(
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
            "model_switches": model_provider_switches,
            "key_switches": int(getattr(self, "key_switches", 0) or 0),
            "keys_available": int(getattr(getattr(self, "keys", None), "count", 0) or 0),
            "active_key": (getattr(getattr(self, "keys", None), "label", lambda: "")()),
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

    def provider_status(self) -> Dict:
        base = dict(super().provider_status())
        base["process_cooldowns"] = provider_health.snapshot()
        return base


__all__ = ["ResilientReasoning", "ProviderResult", "ReasoningProvider", "QuotaExhausted"]
