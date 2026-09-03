"""Release-branch CI coverage regression.

The integration branch is where ChatGPT combines security/storage/provider work
with Claude's research changes. A workflow that only runs on an old maturity
branch can silently leave the exact integration head untested. These checks keep
all three mandatory offline gates attached to `chatgpt-upload-safety` pushes.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
BRANCH = "chatgpt-upload-safety"


def _text(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_mandatory_workflows_cover_integration_branch_pushes():
    for name in (
        "foundation-tests.yml",
        "model-reality-attestors.yml",
        "anti-confirmation-attestor.yml",
    ):
        text = _text(name)
        assert "push:" in text, name
        assert BRANCH in text, name


def test_mandatory_workflows_remain_zero_cost_offline():
    foundation = _text("foundation-tests.yml")
    reality = _text("model-reality-attestors.yml")
    anti = _text("anti-confirmation-attestor.yml")

    assert 'ZERO_COST_ONLY: "true"' in foundation
    assert 'GEMINI_API_KEY: ""' in foundation
    assert 'GEMINI_ZERO_COST_CONFIRMED: "false"' in foundation

    assert 'ZERO_COST_ONLY: "true"' in reality
    assert 'GEMINI_API_KEY: ""' in reality
    assert 'GEMINI_ZERO_COST_CONFIRMED: "false"' in reality

    assert 'ZERO_COST_ONLY: "true"' in anti
    assert 'INFINITY_OFFLINE_TEST: "true"' in anti


def test_workflows_keep_read_only_repo_permissions():
    for name in (
        "foundation-tests.yml",
        "model-reality-attestors.yml",
        "anti-confirmation-attestor.yml",
    ):
        text = _text(name)
        assert "permissions:" in text, name
        assert "contents: read" in text, name
        assert "contents: write" not in text, name
