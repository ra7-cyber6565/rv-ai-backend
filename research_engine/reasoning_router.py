"""Quota-resilient reasoning router for the ₹0 project policy.

The existing GeminiReasoning class remains the primary implementation and keeps
its prompt-building/retry behaviour.  This module subclasses it and adds a
provider-level fallback chain for a *single logical reasoning pass*:

    Gemini free tier -> Groq free account (explicitly confirmed) ->
    OpenRouter free-only router -> local Ollama -> existing evidence-only
    fallback in the orchestrator.

Important safety properties:
- No paid provider is ever selected implicitly.
- OpenRouter is restricted to ``openrouter/free`` or a ``:free`` model while
  ZERO_COST_ONLY is enabled.
- Groq is disabled in ZERO_COST_ONLY unless the owner explicitly confirms the
  API key belongs to a free/no-billing account.
- Ollama is restricted to localhost in ZERO_COST_ONLY.
- A provider quota/auth failure is remembered for the current research run so
  later passes do not repeatedly waste calls on a known-dead provider.
- Intermediate provider errors are kept out of the user-facing error list when
  a later fallback succeeds; raw details remain available only in the technical
  audit.

This file performs no network call at import time.  Provider HTTP libraries are
imported lazily inside ``generate``.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlparse

from .gemini_reasoning import GeminiReasoning as _GeminiReasoning
from .gemini_reasoning import QuotaExhausted

_TRUTHY = {"1", "true", "yes", "on"}


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in _TRUTHY


def _zero_cost() -> bool:
    return _truthy(os.getenv("ZERO_COST_ONLY", "true"))


def _openrouter_model_is_free(model: str) -> bool:
    value = str(model or "").strip().lower()
    return value == "openrouter/free" or value.endswith(":free")


def _local_ollama_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and parsed.hostname in {
            "127.0.0.1", "localhost", "::1"
        }
    except Exception:
        return False


def _clean_model_text(text: str) -> str:
    """Drop common hidden-reasoning wrappers before text reaches the report."""
    body = str(text or "").strip()
    if not body:
        return ""
    body = re.sub(r"<think>.*?</think>", "", body, flags=re.I | re.S)
    body = re.sub(r"<analysis>.*?</analysis>", "", body, flags=re.I | re.S)
    return body.strip()


def _short_technical(value: object, limit: int = 500) -> str:
    return " ".join(str(value or "").split())[:limit]


@dataclass
class ProviderResult:
    text: str = ""
    provider: str = ""
    model: str = ""
    attempts: int = 0
    kind: str = ""
    human: str = ""
    technical: str = ""
    block_for_run: bool = False

    @property
    def ok(self) -> bool:
        return bool(self.text.strip())


class ReasoningProvider:
    name = "provider"
    model = ""

    @property
    def configured(self) -> bool:
        return True

    def generate(self, prompt: str, label: str = "") -> ProviderResult:
        raise NotImplementedError


class OpenAICompatibleFreeProvider(ReasoningProvider):
    """Small requests-based adapter used for Groq/OpenRouter fallbacks."""

    def __init__(
        self,
        *,
        name: str,
        endpoint: str,
        key_env: str,
        model: str,
        confirm_env: str = "",
        timeout_env: str = "REASONING_FALLBACK_TIMEOUT_SECONDS",
    ):
        self.name = name
        self.endpoint = endpoint
        self.key_env = key_env
        self.model = model
        self.confirm_env = confirm_env
        try:
            self.timeout = max(8, min(120, int(os.getenv(timeout_env, "45"))))
        except Exception:
            self.timeout = 45

    @property
    def configured(self) -> bool:
        if not str(os.getenv(self.key_env, "")).strip():
            return False
        if _zero_cost() and self.confirm_env and not _truthy(os.getenv(self.confirm_env, "")):
            return False
        if _zero_cost() and self.name == "openrouter" and not _openrouter_model_is_free(self.model):
            return False
        return True

    @staticmethod
    def _content(payload: Dict) -> str:
        try:
            content = payload.get("choices", [])[0].get("message", {}).get("content", "")
        except Exception:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") in {"text", "output_text"}:
                    parts.append(str(item.get("text") or ""))
            return "\n".join(p for p in parts if p)
        return str(content or "")

    def generate(self, prompt: str, label: str = "") -> ProviderResult:
        if not self.configured:
            return ProviderResult(
                provider=self.name, model=self.model, kind="not_configured",
                human=f"{self.name} free fallback configured nahi hai.",
                block_for_run=True,
            )
        try:
            import requests  # lazy

            headers = {
                "Authorization": f"Bearer {os.getenv(self.key_env, '').strip()}",
                "Content-Type": "application/json",
            }
            if self.name == "openrouter":
                headers["X-Title"] = "Infinity Research AI"
            response = requests.post(
                self.endpoint,
                headers=headers,
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.15,
                    "max_tokens": 6000,
                    "stream": False,
                },
                timeout=(10, self.timeout),
            )
            status = int(getattr(response, "status_code", 0) or 0)
            if status == 200:
                try:
                    payload = response.json()
                except Exception as exc:
                    return ProviderResult(
                        provider=self.name, model=self.model, attempts=1,
                        kind="invalid_response", human=f"{self.name} ne valid JSON nahi diya.",
                        technical=f"{type(exc).__name__}: {_short_technical(exc)}",
                    )
                text = _clean_model_text(self._content(payload))
                if text:
                    return ProviderResult(
                        text=text, provider=self.name, model=self.model, attempts=1,
                    )
                return ProviderResult(
                    provider=self.name, model=self.model, attempts=1,
                    kind="empty_response", human=f"{self.name} se khaali response aaya.",
                    technical=_short_technical(payload),
                )

            detail = _short_technical(getattr(response, "text", ""))
            if status == 429:
                return ProviderResult(
                    provider=self.name, model=self.model, attempts=1,
                    kind="quota", human=f"{self.name} free quota/rate limit abhi available nahi hai.",
                    technical=f"HTTP 429 {detail}", block_for_run=True,
                )
            if status in {401, 403}:
                return ProviderResult(
                    provider=self.name, model=self.model, attempts=1,
                    kind="auth", human=f"{self.name} key/permission valid nahi hai.",
                    technical=f"HTTP {status} {detail}", block_for_run=True,
                )
            if status == 404:
                return ProviderResult(
                    provider=self.name, model=self.model, attempts=1,
                    kind="model_unavailable", human=f"{self.name} ka configured model available nahi hai.",
                    technical=f"HTTP 404 {detail}", block_for_run=True,
                )
            if status >= 500 or status in {408, 409, 425}:
                return ProviderResult(
                    provider=self.name, model=self.model, attempts=1,
                    kind="temporary", human=f"{self.name} temporary unavailable hai.",
                    technical=f"HTTP {status} {detail}",
                )
            return ProviderResult(
                provider=self.name, model=self.model, attempts=1,
                kind="provider_error", human=f"{self.name} request complete nahi hui.",
                technical=f"HTTP {status} {detail}",
            )
        except Exception as exc:
            return ProviderResult(
                provider=self.name, model=self.model, attempts=1,
                kind="network", human=f"{self.name} se connection nahi ban paaya.",
                technical=f"{type(exc).__name__}: {_short_technical(exc)}",
            )


class OllamaProvider(ReasoningProvider):
    name = "ollama"

    def __init__(self):
        self.model = str(os.getenv("OLLAMA_MODEL", "qwen3:4b")).strip() or "qwen3:4b"
        self.base_url = str(os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
        try:
            self.timeout = max(15, min(300, int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120"))))
        except Exception:
            self.timeout = 120

    @property
    def configured(self) -> bool:
        if not _truthy(os.getenv("OLLAMA_ENABLED", "false")):
            return False
        if _zero_cost() and not _local_ollama_url(self.base_url):
            return False
        return True

    def generate(self, prompt: str, label: str = "") -> ProviderResult:
        if not self.configured:
            return ProviderResult(
                provider=self.name, model=self.model, kind="not_configured",
                human="Local Ollama fallback enabled/configured nahi hai.",
                block_for_run=True,
            )
        try:
            import requests  # lazy

            response = requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "think": False,
                    "options": {"temperature": 0.15},
                },
                timeout=(3, self.timeout),
            )
            status = int(getattr(response, "status_code", 0) or 0)
            if status == 200:
                payload = response.json()
                text = _clean_model_text((payload.get("message") or {}).get("content", ""))
                if text:
                    return ProviderResult(text=text, provider=self.name, model=self.model, attempts=1)
                return ProviderResult(
                    provider=self.name, model=self.model, attempts=1,
                    kind="empty_response", human="Local Ollama se khaali response aaya.",
                    technical=_short_technical(payload),
                )
            detail = _short_technical(getattr(response, "text", ""))
            return ProviderResult(
                provider=self.name, model=self.model, attempts=1,
                kind="local_model_unavailable" if status == 404 else "local_error",
                human=("Local Ollama model installed nahi mila." if status == 404
                       else "Local Ollama response available nahi hua."),
                technical=f"HTTP {status} {detail}", block_for_run=status == 404,
            )
        except Exception as exc:
            return ProviderResult(
                provider=self.name, model=self.model, attempts=1,
                kind="local_unavailable", human="Local Ollama abhi reachable nahi hai.",
                technical=f"{type(exc).__name__}: {_short_technical(exc)}",
                block_for_run=True,
            )


def _default_fallbacks() -> List[ReasoningProvider]:
    chain = [p.strip().lower() for p in str(
        os.getenv("REASONING_FALLBACK_CHAIN", "groq,openrouter,ollama")
    ).split(",") if p.strip()]
    providers: Dict[str, ReasoningProvider] = {
        "groq": OpenAICompatibleFreeProvider(
            name="groq",
            endpoint="https://api.groq.com/openai/v1/chat/completions",
            key_env="GROQ_API_KEY",
            model=str(os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")).strip()
                  or "openai/gpt-oss-120b",
            confirm_env="GROQ_ZERO_COST_CONFIRMED",
        ),
        "openrouter": OpenAICompatibleFreeProvider(
            name="openrouter",
            endpoint="https://openrouter.ai/api/v1/chat/completions",
            key_env="OPENROUTER_API_KEY",
            model=str(os.getenv("OPENROUTER_MODEL", "openrouter/free")).strip()
                  or "openrouter/free",
        ),
        "ollama": OllamaProvider(),
    }
    out: List[ReasoningProvider] = []
    seen = set()
    for name in chain:
        provider = providers.get(name)
        if provider is None or name in seen or not provider.configured:
            continue
        seen.add(name)
        out.append(provider)
    return out


class ResilientReasoning(_GeminiReasoning):
    """GeminiReasoning with free provider-level fallback for each logical pass."""

    def __init__(self, *args, fallback_providers: Optional[Iterable[ReasoningProvider]] = None,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self.fallback_providers = list(
            fallback_providers if fallback_providers is not None else _default_fallbacks()
        )
        self.provider_attempts: Dict[str, int] = {}
        self.provider_successes: Dict[str, int] = {}
        self.provider_failures: Dict[str, int] = {}
        self.provider_switches = 0
        self.blocked_providers: Dict[str, str] = {}
        self._router_technical: List[str] = []
        self._router_last_success: Optional[bool] = None
        self._router_last_failure_kind = ""
        self._router_last_failure_reason = ""
        self._primary_blocked_for_run = False
        self._fallback_http_attempts = 0

    @property
    def router_active(self) -> bool:
        return bool(self.fallback_providers)

    @staticmethod
    def _gemini_allowed() -> bool:
        key = str(os.getenv("GEMINI_API_KEY", "")).strip()
        if not key:
            return False
        if _zero_cost() and not _truthy(os.getenv("GEMINI_ZERO_COST_CONFIRMED", "")):
            return False
        return True

    def _remember_model(self, provider: str, model: str) -> None:
        value = f"{provider}/{model}" if model else provider
        if value and value not in self.models_tried:
            self.models_tried.append(value)

    def _record_fallback_failure(self, result: ProviderResult, label: str) -> None:
        self.provider_failures[result.provider] = self.provider_failures.get(result.provider, 0) + 1
        if result.technical:
            self._router_technical.append(
                f"{result.provider}/{result.model} / {label}: {result.kind} — {result.technical}"
            )
        if result.block_for_run:
            self.blocked_providers[result.provider] = result.kind or "unavailable"

    def generate(self, prompt: str, label: str = "") -> str:
        # With no configured fallback the class intentionally behaves exactly
        # like Claude's GeminiReasoning, preserving existing tests/callers.
        if not self.router_active:
            return super().generate(prompt, label)

        if self.remaining <= 0:
            raise QuotaExhausted(f"call budget ({self.budget}) khatam — '{label}' skip hua")

        tag = label or "reasoning"
        self._router_last_success = False
        self._router_last_failure_kind = ""
        self._router_last_failure_reason = ""

        # Primary Gemini attempt.  If it already failed with a hard quota/auth
        # condition in this run, skip it instead of burning every later pass.
        primary_text = ""
        before_errors = len(self.errors)
        before_events = len(getattr(self.ledger, "events", []))
        if not self._primary_blocked_for_run and self._gemini_allowed():
            primary_text = super().generate(prompt, tag)
        else:
            # super().generate normally consumes one logical budget unit. We
            # still consume exactly one because fallback is the same logical pass.
            self.calls_used += 1

        if primary_text:
            self._router_last_success = True
            return primary_text

        # Intermediate Gemini failures must not become a user warning if a
        # fallback completes this same logical pass. Keep them only in technical audit.
        new_errors = list(self.errors[before_errors:])
        del self.errors[before_errors:]
        for raw in new_errors:
            self._router_technical.append(f"gemini/{tag}: {_short_technical(raw)}")
        events = list(getattr(self.ledger, "events", []))[before_events:]
        hard_kinds = {str(e.get("kind") or "") for e in events if isinstance(e, dict)}
        if hard_kinds.intersection({"daily_quota", "auth", "permission", "quota"}):
            self._primary_blocked_for_run = True

        attempted_provider = False
        for provider in self.fallback_providers:
            if provider.name in self.blocked_providers:
                continue
            attempted_provider = True
            self.provider_attempts[provider.name] = self.provider_attempts.get(provider.name, 0) + 1
            result = provider.generate(prompt, tag)
            self._fallback_http_attempts += int(result.attempts or 0)
            self.attempts += int(result.attempts or 0)
            self._remember_model(result.provider, result.model)
            if result.ok:
                self.successes += 1
                self.provider_successes[result.provider] = (
                    self.provider_successes.get(result.provider, 0) + 1
                )
                self.provider_switches += 1
                self.notes.append(
                    f"{tag}: primary reasoning available nahi thi; {result.provider} "
                    f"free fallback ({result.model}) ne pass complete kiya."
                )
                self._router_last_success = True
                self._router_last_failure_kind = ""
                self._router_last_failure_reason = ""
                return result.text
            self._record_fallback_failure(result, tag)

        self._router_last_failure_kind = "all_free_providers_unavailable"
        self._router_last_failure_reason = (
            "configured free reasoning providers is pass mein available nahi the"
            if attempted_provider else
            "koi free fallback provider configured/available nahi tha"
        )
        self.errors.append(
            f"{tag}: {self._router_last_failure_reason}; local evidence-only fallback use hoga."
        )
        return ""

    def failure_kind(self) -> str:
        if self.router_active and self._router_last_success is True:
            return ""
        if self.router_active and self._router_last_failure_kind:
            return self._router_last_failure_kind
        return super().failure_kind()

    def failure_reason(self) -> str:
        if self.router_active and self._router_last_success is True:
            return ""
        if self.router_active and self._router_last_failure_reason:
            return self._router_last_failure_reason
        return super().failure_reason()

    def technical_details(self, limit: int = 8) -> List[str]:
        if not self.router_active:
            return super().technical_details(limit=limit)
        rows: List[str] = []
        for item in list(super().technical_details(limit=limit)) + self._router_technical:
            clean = _short_technical(item)
            if clean and clean not in rows:
                rows.append(clean)
            if len(rows) >= limit:
                break
        return rows

    def usage_note(self) -> str:
        if not self.router_active:
            return super().usage_note()
        bits = [f"{self.calls_used}/{self.budget} logical reasoning pass"]
        bits.append(f"{self.successes} pass output ke saath complete")
        if self.attempts:
            bits.append(f"{self.attempts} provider/API attempts")
        if self.provider_switches:
            bits.append(f"{self.provider_switches} pass free backup provider par complete")
        if self.blocked_providers:
            bits.append("run ke liye skip: " + ", ".join(
                f"{name} ({kind})" for name, kind in sorted(self.blocked_providers.items())
            ))
        return ", ".join(bits)

    def api_accounting(self) -> Dict:
        if not self.router_active:
            return super().api_accounting()
        primary = super().api_accounting()
        # Claude is separately hardening same-model retry accounting.  Prefer
        # the explicit field when available; otherwise do not invent a number.
        same_model_retries = primary.get("same_model_retries")
        return {
            "logical_reasoning_calls": self.calls_used,
            "budget": self.budget,
            "actual_http_attempts": self.attempts,
            "successful_calls": self.successes,
            "failed_attempts": max(0, self.attempts - self.successes),
            "retries": same_model_retries if same_model_retries is not None else 0,
            "same_model_retries": same_model_retries,
            "provider_fallbacks": self.provider_switches,
            "provider_attempts": dict(self.provider_attempts),
            "provider_successes": dict(self.provider_successes),
            "provider_failures": dict(self.provider_failures),
            "models_tried": list(self.models_tried),
            "model_switches": primary.get("model_switches", self.switched_models),
            "blocked_models": dict(getattr(self, "blocked", {}) or {}),
            "blocked_providers": dict(self.blocked_providers),
            "failure_kinds": primary.get("failure_kinds", []),
            "primary_failure_kind": primary.get("primary_failure_kind", ""),
            "failure_events": list(primary.get("failure_events", []) or [])[:20],
            "failure_summary": self.failure_reason(),
            "stopped_early": bool(self.failure_kind() and not self._router_last_success),
        }

    def provider_status(self) -> Dict:
        return {
            "router_active": self.router_active,
            "zero_cost_only": _zero_cost(),
            "gemini_enabled": self._gemini_allowed(),
            "fallbacks": [
                {"provider": p.name, "model": p.model, "configured": p.configured}
                for p in self.fallback_providers
            ],
            "blocked_for_run": dict(self.blocked_providers),
        }


__all__ = [
    "ProviderResult", "ReasoningProvider", "OpenAICompatibleFreeProvider",
    "OllamaProvider", "ResilientReasoning", "QuotaExhausted",
    "_openrouter_model_is_free", "_local_ollama_url",
]
