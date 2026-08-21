"""Offline regression for bounded model calls and private browser recovery."""
from __future__ import annotations

import inspect
import os
from pathlib import Path

from research_engine import chat as chat_mod
from research_engine import gemini_model


ROOT = Path(__file__).resolve().parents[1]
WEB_PAGE = ROOT / "web" / "index.html"
PASS = 0
FAIL = 0


def check(name: str, condition: object, extra: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f" — {extra}" if extra else ""))


class _Resp:
    def __init__(self, text: str):
        self.text = text


class _NewSdkModel:
    def __init__(self, text: str = "jawab", boom: Exception | None = None):
        self.text = text
        self.boom = boom
        self.seen = []

    def generate_content(self, prompt, request_options=None):
        self.seen.append({"prompt": prompt, "request_options": request_options})
        if self.boom is not None:
            raise self.boom
        return _Resp(self.text)


class _OldSdkModel:
    def __init__(self, text: str = "jawab"):
        self.text = text
        self.calls = 0

    def generate_content(self, prompt):
        self.calls += 1
        return _Resp(self.text)


def _model_timeout_checks() -> None:
    print("\n[1] shared Gemini call boundary")
    model = _NewSdkModel("theek")
    result = gemini_model.generate(model, "hello")
    check("jawab unchanged", result.text == "theek")
    options = model.seen[0]["request_options"] or {}
    check("request_options timeout present", isinstance(options.get("timeout"), int))
    gemini_model.generate(model, "hello", timeout=33)
    check("caller timeout respected", model.seen[1]["request_options"]["timeout"] == 33)

    old = _OldSdkModel("legacy")
    check("legacy SDK still works", gemini_model.generate(old, "hi").text == "legacy")
    check("legacy call not duplicated", old.calls == 1)

    boom = _NewSdkModel(boom=RuntimeError("429 quota"))
    raised = ""
    try:
        gemini_model.generate(boom, "hi")
    except RuntimeError as exc:
        raised = str(exc)
    check("provider error reaches resilient router", raised == "429 quota")

    original = os.environ.get("GEMINI_CALL_TIMEOUT")
    try:
        os.environ["GEMINI_CALL_TIMEOUT"] = "1"
        check("timeout lower bound", gemini_model.call_timeout() == 10)
        os.environ["GEMINI_CALL_TIMEOUT"] = "99999"
        check("timeout upper bound", gemini_model.call_timeout() == 600)
        os.environ["GEMINI_CALL_TIMEOUT"] = "invalid"
        check("invalid timeout falls back", 10 <= gemini_model.call_timeout() <= 600)
    finally:
        if original is None:
            os.environ.pop("GEMINI_CALL_TIMEOUT", None)
        else:
            os.environ["GEMINI_CALL_TIMEOUT"] = original


def _provider_boundary_checks() -> None:
    print("\n[2] QUICK chat keeps shared provider routing")
    source = inspect.getsource(chat_mod)
    check("resilient reasoning facade used", "ResilientReasoning" in source)
    for forbidden in ("google.generativeai", "KeyPool(", "candidates(genai)",
                      "GenerativeModel("):
        check(f"no direct provider path: {forbidden}",
              forbidden not in source, forbidden)


def _browser_checks() -> None:
    print("\n[3] browser recovery and persistent progress")
    page = WEB_PAGE.read_text(encoding="utf-8")
    code = "\n".join(
        line for line in page.splitlines()
        if not line.strip().startswith("//")
    )

    check("one centralized fetch implementation",
          code.count("fetch(") == 1, str(code.count("fetch(")))
    check("response body parsed safely", "await r.text()" in page and ".json()" not in code)
    check("network calls are no-store", 'cache:"no-store"' in page)
    check("browser timeout is bounded", "AbortController" in page and "ctrl.abort()" in page)
    check("transient QUICK retry exists", "await sleep(1500)" in page)
    check("HTTP failures are distinguished",
          "clientFailure(" in page and "code===429" in page and "code===503" in page)
    failure = page.split("function clientFailure(")[1].split("function restoreQuestion")[0]
    check("raw response body is never rendered", ".raw" not in failure)

    check("server-issued project capability preserved",
          "/api/v1/session" in page and "X-Project-Token" in page)
    check("durable job capability preserved",
          "X-Research-Job-Token" in page and "/api/v1/research-jobs/" in page)
    check("insecure public history recovery not introduced",
          "/api/v1/history/" not in page)

    check("30-minute hard deadline present", "30*60*1000" in page)
    check("stalled progress guard present", "6*60*1000" in page and "lastChange" in page)
    check("single live progress writer", code.count("paintProgress(ui,p);") == 1)

    check("completed research process remains visible",
          "appendResearchProcess" in page and "data?.research_progress" in page)
    check("process fields rendered with textContent",
          'summary.textContent=' in page and 'log.textContent=' in page)
    check("source URL scheme guard preserved", "function safeHttpUrl(" in page)
    check("external links hardened",
          'rel="noopener noreferrer nofollow"' in page)


def main() -> int:
    global PASS, FAIL
    PASS = 0
    FAIL = 0
    _model_timeout_checks()
    _provider_boundary_checks()
    _browser_checks()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


def test_chat_resilience_all_checks_pass():
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
