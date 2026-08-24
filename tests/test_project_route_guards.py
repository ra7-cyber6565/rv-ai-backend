"""Offline route tests for project capability isolation.

These tests prove the guard runs before model/search/upload job work. They do not
call any network/model provider.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from api import agent_routes, exam_routes, job_routes, routes, session_routes
from utils import project_guard


_VALID_PROJECT = "p_" + "x" * 24


class _DenyAccess:
    def verify(self, project_id, token):  # noqa: ARG002
        return False


class _AllowAccess:
    def verify(self, project_id, token):
        return project_id == _VALID_PROJECT and token == "good-token"


def test_project_guard_uses_same_404_for_missing_wrong_or_bad_project(monkeypatch):
    monkeypatch.setattr(project_guard, "project_access", _DenyAccess())
    for project, token in (
        (_VALID_PROJECT, None),
        (_VALID_PROJECT, "wrong"),
        ("default", "good-token"),
    ):
        with pytest.raises(HTTPException) as exc:
            project_guard.require_project_access(project, token)
        assert exc.value.status_code == 404
        assert exc.value.detail == "Project session nahi mila"


def test_project_guard_accepts_matching_capability(monkeypatch):
    monkeypatch.setattr(project_guard, "project_access", _AllowAccess())
    assert project_guard.require_project_access(_VALID_PROJECT, "good-token") is None


def test_session_route_returns_only_project_capability_material(monkeypatch):
    class FakeAccess:
        def status(self):
            return {"project_capability_tokens_ready": True}

        def create(self):
            return {
                "project_id": _VALID_PROJECT,
                "project_access_token": "opaque-project-token",
                "project_access_header": "X-Project-Token",
            }

    monkeypatch.setattr(session_routes, "project_access", FakeAccess())
    result = session_routes.create_session()
    assert result["project_id"] == _VALID_PROJECT
    assert result["project_access_token"] == "opaque-project-token"
    assert result["project_access_header"] == "X-Project-Token"
    dumped = repr(result).lower()
    assert "secret_path" not in dumped
    assert "api_key" not in dumped
    assert "oauth" not in dumped


def test_session_route_fails_closed_when_signer_not_ready(monkeypatch):
    class BrokenAccess:
        def status(self):
            return {"project_capability_tokens_ready": False}

    monkeypatch.setattr(session_routes, "project_access", BrokenAccess())
    with pytest.raises(HTTPException) as exc:
        session_routes.create_session()
    assert exc.value.status_code == 503


def test_chat_guard_runs_before_quick_model_or_research(monkeypatch):
    called = {"research": 0}

    def deny(*_args):
        raise HTTPException(status_code=404, detail="Project session nahi mila")

    monkeypatch.setattr(agent_routes, "require_project_access", deny)
    monkeypatch.setattr(
        agent_routes.manager,
        "research",
        lambda **_kwargs: called.__setitem__("research", called["research"] + 1),
    )
    request = agent_routes.ChatRequest(message="hello", project_id=_VALID_PROJECT)
    with pytest.raises(HTTPException) as exc:
        agent_routes.chat(request, None)
    assert exc.value.status_code == 404
    assert called["research"] == 0


def test_deep_research_guard_runs_before_manager(monkeypatch):
    called = {"research": 0}

    def deny(*_args):
        raise HTTPException(status_code=404, detail="Project session nahi mila")

    monkeypatch.setattr(agent_routes, "require_project_access", deny)
    monkeypatch.setattr(
        agent_routes.manager,
        "research",
        lambda **_kwargs: called.__setitem__("research", called["research"] + 1),
    )
    request = agent_routes.DeepResearchRequest(question="why", project_id=_VALID_PROJECT)
    with pytest.raises(HTTPException) as exc:
        agent_routes.deep_research(request, "wrong")
    assert exc.value.status_code == 404
    assert called["research"] == 0


def test_async_job_start_guard_runs_before_queue_submit(monkeypatch):
    class FakeRunner:
        def __init__(self):
            self.calls = 0

        def submit(self, **_kwargs):
            self.calls += 1
            raise AssertionError("submit must not run before project authorization")

    fake = FakeRunner()

    def deny(*_args):
        raise HTTPException(status_code=404, detail="Project session nahi mila")

    monkeypatch.setattr(job_routes, "require_project_access", deny)
    monkeypatch.setattr(job_routes, "runner", fake)
    request = job_routes.ResearchJobRequest(question="why", project_id=_VALID_PROJECT)
    with pytest.raises(HTTPException) as exc:
        job_routes.start_research_job(request, "wrong")
    assert exc.value.status_code == 404
    assert fake.calls == 0


def test_ask_guard_runs_before_research_manager(monkeypatch):
    called = {"research": 0}

    def deny(*_args):
        raise HTTPException(status_code=404, detail="Project session nahi mila")

    monkeypatch.setattr(routes, "require_project_access", deny)
    monkeypatch.setattr(
        routes.manager,
        "research",
        lambda **_kwargs: called.__setitem__("research", called["research"] + 1),
    )
    request = routes.QuestionRequest(question="why", project_id=_VALID_PROJECT)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes.ask(request, "wrong"))
    assert exc.value.status_code == 404
    assert called["research"] == 0


def test_exam_analysis_guard_runs_before_forecast_engine(monkeypatch):
    called = {"analysis": 0}

    class SpyEngine:
        def analyze(self, **_kwargs):
            called["analysis"] += 1
            return {}

    def deny(*_args):
        raise HTTPException(status_code=404, detail="Project session nahi mila")

    monkeypatch.setattr(exam_routes, "require_project_access", deny)
    monkeypatch.setattr(exam_routes, "ExamIntelligenceEngine", lambda: SpyEngine())
    request = exam_routes.ExamIntelligenceRequest(
        exam_name="RPF SI",
        project_id=_VALID_PROJECT,
        as_of="2030-01-01",
        syllabus=[{
            "topic_id": "T1", "subject": "Math", "chapter": "Number",
            "topic": "Percentage",
        }],
        papers=[{
            "paper_id": "P1", "held_on": "2028-01-01",
            "questions": [{
                "question_id": "Q1", "text": "Percentage question",
                "topic_ids": ["T1"],
            }],
        }],
    )
    with pytest.raises(HTTPException) as exc:
        exam_routes.analyze_exam(request, "wrong")
    assert exc.value.status_code == 404
    assert called["analysis"] == 0


def test_all_project_scoped_rag_routes_contain_guard_before_processing():
    root = Path(__file__).resolve().parents[1]
    text = (root / "api" / "routes.py").read_text(encoding="utf-8")
    names = (
        "upload_audio",
        "upload_document",
        "upload_pdf",
        "ingest_youtube",
        "transcribe_audio",
        "ask",
    )
    for index, name in enumerate(names):
        start = text.index(f"def {name}(") if f"def {name}(" in text else text.index(f"async def {name}(")
        next_positions = []
        for other in names[index + 1:]:
            for marker in (f"def {other}(", f"async def {other}("):
                pos = text.find(marker, start + 1)
                if pos >= 0:
                    next_positions.append(pos)
        end = min(next_positions) if next_positions else len(text)
        block = text[start:end]
        assert "require_project_access(" in block, name
