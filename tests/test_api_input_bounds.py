"""Offline schema tests for bounded public JSON inputs."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.agent_routes import ChatRequest, DeepResearchRequest
from api.job_routes import ResearchJobRequest


@pytest.mark.parametrize(
    "factory,field",
    [
        (lambda text: ChatRequest(message=text), "message"),
        (lambda text: DeepResearchRequest(question=text), "question"),
        (lambda text: ResearchJobRequest(question=text), "question"),
    ],
)
def test_public_question_like_fields_reject_over_20k(factory, field):
    ok = factory("x" * 20_000)
    assert getattr(ok, field) == "x" * 20_000
    with pytest.raises(ValidationError):
        factory("x" * 20_001)


@pytest.mark.parametrize(
    "factory",
    [
        lambda project: ChatRequest(message="hi", project_id=project),
        lambda project: DeepResearchRequest(question="why", project_id=project),
        lambda project: ResearchJobRequest(question="why", project_id=project),
    ],
)
def test_public_project_ids_are_bounded(factory):
    assert len(factory("p" * 80).project_id) == 80
    with pytest.raises(ValidationError):
        factory("p" * 81)


def test_empty_questions_are_rejected_before_engine_call():
    with pytest.raises(ValidationError):
        ChatRequest(message="")
    with pytest.raises(ValidationError):
        DeepResearchRequest(question="")
    with pytest.raises(ValidationError):
        ResearchJobRequest(question="")
