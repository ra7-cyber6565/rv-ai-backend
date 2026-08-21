"""Offline tests for QUICK chat provider failover and safe route fallback."""
from __future__ import annotations

import os

from research_engine import chat as chat_module


def _clear_model_env(monkeypatch):
    for key in (
        "GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY",
        "GEMINI_ZERO_COST_CONFIRMED", "GROQ_ZERO_COST_CONFIRMED",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ZERO_COST_ONLY", "true")
    monkeypatch.setenv("OLLAMA_ENABLED", "false")


def test_trivial_greeting_uses_zero_api_calls(monkeypatch):
    _clear_model_env(monkeypatch)
    result = chat_module.quick_chat("hello")
    assert result["ok"] is True
    assert result["reasoning_layer"] == "deterministic_smalltalk"
    assert result["api_attempts"] == 0
    assert result.get("fallback_required") in (None, False)


def test_no_model_nontrivial_question_requests_evidence_fallback(monkeypatch):
    _clear_model_env(monkeypatch)
    result = chat_module.quick_chat("Why does superconductivity break above a critical temperature?")
    assert result["ok"] is False
    assert result["fallback_required"] is True
    assert result["reason"] == "no_model_layer_configured"
    assert "detail" not in result
    assert "api" not in str(result).lower() or "api_attempts" in result


def test_configured_backup_can_complete_quick_chat(monkeypatch):
    class FakeBrain:
        def __init__(self, *args, **kwargs):
            pass

        def generate(self, prompt, label):
            assert label == "quick_chat"
            assert "User ka naya message" in prompt
            return "backup answer"

        def api_accounting(self):
            return {
                "logical_reasoning_calls": 1,
                "passes_requested": 1,
                "passes_with_output": 1,
                "actual_http_attempts": 2,
                "same_model_retries": 0,
                "model_switches": 1,
                "provider_fallbacks": 1,
                "blocked_models": {},
                "blocked_providers": {"gemini": "quota"},
            }

    monkeypatch.setattr(chat_module, "reasoning_status", lambda: {"model_layers_configured": 2})
    monkeypatch.setattr(chat_module, "ResilientReasoning", FakeBrain)
    result = chat_module.quick_chat("Explain entropy simply")
    assert result["ok"] is True
    assert result["answer"] == "backup answer"
    assert result["degraded"] is True
    assert result["reasoning_accounting"]["provider_fallbacks"] == 1
    assert "detail" not in result


def test_unexpected_provider_exception_becomes_route_fallback_signal(monkeypatch):
    class ExplodingBrain:
        def __init__(self, *args, **kwargs):
            pass

        def generate(self, prompt, label):  # noqa: ARG002
            raise RuntimeError("TOP-SECRET raw provider traceback")

        def api_accounting(self):
            return {"actual_http_attempts": 1, "passes_with_output": 0}

    monkeypatch.setattr(chat_module, "reasoning_status", lambda: {"model_layers_configured": 1})
    monkeypatch.setattr(chat_module, "ResilientReasoning", ExplodingBrain)
    result = chat_module.quick_chat("Explain quantum tunneling")
    assert result["fallback_required"] is True
    assert result["ok"] is False
    assert "TOP-SECRET" not in str(result)
    assert "traceback" not in str(result).lower()


def test_history_is_bounded_to_protect_free_quota():
    history = [
        {"role": "user", "content": "x" * 5000},
        {"role": "assistant", "content": "y" * 5000},
        {"role": "user", "content": "z" * 5000},
        {"role": "assistant", "content": "q" * 5000},
    ]
    block = chat_module._history_block(history)
    assert len(block) <= chat_module._MAX_HISTORY_CHARS + 50


def test_large_quick_message_is_not_silently_truncated(monkeypatch):
    _clear_model_env(monkeypatch)
    result = chat_module.quick_chat("a" * (chat_module._MAX_MESSAGE_CHARS + 1))
    assert result["ok"] is True
    assert result["degraded"] is True
    assert result["reason"] == "message_too_large_for_quick_chat"
    assert result["fallback_required"] is False


def test_chat_diag_is_read_only_status(monkeypatch):
    from api import agent_routes

    called = {"n": 0}

    def fake_status():
        called["n"] += 1
        return {"model_layers_configured": 3, "deterministic_last_resort": True}

    monkeypatch.setattr(agent_routes, "reasoning_status", fake_status)
    result = agent_routes.chat_diag()
    assert called["n"] == 1
    assert result["deterministic_last_resort"] is True
    assert "test_call" not in result
    assert "key_length" not in result


def test_route_moves_failed_chat_to_async_quick_research(monkeypatch):
    from api import agent_routes
    import research_engine.chat as quick_module

    monkeypatch.setattr(agent_routes, "require_project_access", lambda *_args: None)
    monkeypatch.setattr(
        quick_module,
        "quick_chat",
        lambda message, history=None: {
            "answer": "", "ok": False, "fallback_required": True,
            "reason": "all_configured_model_layers_unavailable",
        },
    )
    sync_calls = {"n": 0}

    def forbidden_sync_research(**kwargs):  # noqa: ARG001
        sync_calls["n"] += 1
        raise AssertionError("chat route must not run long research synchronously")

    monkeypatch.setattr(agent_routes.manager, "research", forbidden_sync_research)
    project = "p_" + "a" * 24
    request = agent_routes.ChatRequest(message="hard factual question", project_id=project)
    result = agent_routes.chat(request, "project-token")
    assert result["ok"] is True
    assert result["degraded"] is True
    assert result["fallback_required"] is True
    assert result["start_research_job"] is True
    assert result["research_depth_mode"] == "QUICK"
    assert result["chat_fallback"] == "async_quick_evidence_research"
    assert result["reason"] == "all_configured_model_layers_unavailable"
    assert sync_calls["n"] == 0
    assert "background job" in result["answer"]


def test_route_never_leaks_unknown_fallback_reason(monkeypatch):
    from api import agent_routes
    import research_engine.chat as quick_module

    monkeypatch.setattr(agent_routes, "require_project_access", lambda *_args: None)
    monkeypatch.setattr(
        quick_module,
        "quick_chat",
        lambda message, history=None: {
            "fallback_required": True,
            "ok": False,
            "reason": "SECRET SDK traceback protobuf 429",
        },
    )
    project = "p_" + "b" * 24
    request = agent_routes.ChatRequest(message="question", project_id=project)
    result = agent_routes.chat(request, "project-token")
    assert result["ok"] is True
    assert result["degraded"] is True
    assert result["start_research_job"] is True
    assert result["reason"] == "model_layer_unavailable"
    text = str(result)
    for raw in ("SECRET", "traceback", "protobuf", "429"):
        assert raw.lower() not in text.lower()
