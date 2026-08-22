"""Static safety checks for the shipped Windows/PowerShell launchers."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8-sig")


def test_backend_launcher_is_repo_relative_and_drive_fail_closed():
    text = _read("START_BACKEND.bat")
    lowered = text.lower()
    assert 'cd /d "%~dp0"' in lowered
    assert "c:\\users\\intel" not in lowered
    assert 'findstr /b /c:"infinity_data_root=" ".env"' in lowered
    assert "venv\\scripts\\python.exe" in lowered
    assert 'if not exist "%data_drive%\\"' in lowered
    assert "--host 127.0.0.1 --port 8000" in lowered


def test_powershell_live_launcher_passes_only_non_secret_arguments():
    text = _read("RUN_LIVE_ZERO_COST_GATE.ps1")
    lowered = text.lower()
    assert "$psscriptroot" in lowered
    assert '"--data-root"' in lowered
    assert '"--execute"' in lowered
    assert '"--receipt"' in lowered
    assert "gemini_api_key" not in lowered
    assert "groq_api_key" not in lowered
    assert "openrouter_api_key" not in lowered
    assert "invoke-expression" not in lowered
    assert "start-process" not in lowered


def test_deployment_guide_uses_relative_windows_commands():
    text = _read("DEPLOYMENT_GUIDE.md")
    lowered = text.lower()
    assert ".\\start_backend.bat" in lowered
    assert ".\\run_live_zero_cost_gate.ps1" in lowered
    assert "c:\\users\\intel" not in lowered
    assert "provider key command line par mat likho" in lowered
