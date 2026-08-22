"""Offline regression for bounded model calls and private browser recovery."""
from __future__ import annotations

import inspect
import os
import re
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


# §21 ke tab-rewrite ke baad UI ke helper naam badal gaye: `appendResearchProcess`
# aur `summary.textContent=` / `log.textContent=` wala purana <details> block hata
# kar `processHtml(data)` + escaped render aa gaya. Yahan ke do check sirf PURANE
# NAAM dhoondh rahe the, isliye feature theek hone ke baad bhi fail ho rahe the —
# ek naam-par-tika hua check jhoothi fail deta hai aur asli baat (escaping) prove
# bhi nahi karta. Ab check WAJAH par hai: (1) mukammal run ka process snapshot
# dikhta hai kya, (2) uske fields raw HTML ki tarah inject hote hain kya. Rename se
# ye fail nahi hoga, lekin feature ya escaping hatane par pakka fail hoga.
def _fn_body(page: str, name: str) -> str:
    """`function name(` se agli top-level function tak ka code.

    `async function` par bhi rukna zaroori hai — warna body agle function me
    ghus jaati hai aur wahan ke URL helpers (encodeURIComponent) HTML escaping
    ke check me jhoothi galti bana dete hain.
    """
    marker = "function %s(" % name
    if marker not in page:
        return ""
    tail = page.split(marker, 1)[1]
    cuts = [tail.index(m) for m in ("\nfunction ", "\nasync function ")
            if m in tail]
    return tail[:min(cuts)] if cuts else tail


# `'...'+X+'...'` jaisi seedhi field interpolation. `esc(r.label)` is regex me
# nahi aata, kyunki `+` ke turant baad `esc(` hai — yahi hum chahte hain.
_BARE_FIELD_RE = re.compile(r"\+\s*([A-Za-z_$][\w$]*\.[\w$]+)")
# Field ko kisi aise function me lapet dena bhi hole hai: `String(p.x)` HTML se
# bachata nahi. Isliye concat me jo bhi call juda ho, uska naam allowlist me hona
# chahiye — `esc` (escape karta hai), `Number` (sirf number banata hai) ya wo
# helper jinke escaping ka test isi file me hai.
_CONCAT_CALL_RE = re.compile(r"\+\s*([A-Za-z_$][\w$]*)\s*\(")
_SAFE_CONCAT_CALLS = {"esc", "Number", "stageRowsHtml", "progressCounts",
                      "stageTable", "emptyBox"}
# Ye do value code khud set karta hai (tick/dash aur CSS class), server se nahi
# aati — isliye inko escape kiye bina joda ja sakta hai. Neeche `_markers_are_literal`
# is dawe ko bhi verify karta hai, warna allowlist ek chhupa hua raasta ban jaati.
_CODE_SET_MARKERS = {"r.cls", "r.mk"}
_MARKER_VALUE_RE = re.compile(r"\b(?:mk|cls):([^,}]+)")
_SERVER_FIELD_RE = re.compile(r"\b(?:p|prog|snap|data|ran)\.")


def _unescaped_process_fields(page: str) -> list:
    """Process render path me bina escape jodi gayi server fields."""
    bad = []
    for name in ("processHtml", "stageRowsHtml", "progressCounts", "paintProgress"):
        body = _fn_body(page, name)
        if not body:
            bad.append("%s missing" % name)
            continue
        for field in _BARE_FIELD_RE.findall(body):
            if field not in _CODE_SET_MARKERS:
                bad.append("%s: %s" % (name, field))
        for call in _CONCAT_CALL_RE.findall(body):
            if call not in _SAFE_CONCAT_CALLS:
                bad.append("%s: %s(...)" % (name, call))
    return bad


def _markers_are_literal(page: str) -> bool:
    """`mk`/`cls` sach me literal hain — unme server ka koi field nahi ghusta."""
    body = _fn_body(page, "stageTable")
    values = _MARKER_VALUE_RE.findall(body)
    return bool(values) and not any(_SERVER_FIELD_RE.search(v) for v in values)


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

    check(
        "default 30-minute and Marathon 60-minute deadlines present",
        'requestedMode==="MARATHON"?60:30' in page
        and "*60*1000" in page,
    )
    check("stalled progress guard present", "6*60*1000" in page and "lastChange" in page)
    check("single live progress writer", code.count("paintProgress(ui,p);") == 1)

    check("completed research process remains visible",
          "function processHtml(" in page
          and "data.research_progress" in page
          and "process:processHtml(data)" in page)
    check("missing process snapshot is stated, not faked",
          "p.available!==true" in page and "snapshot nahi aaya" in page)
    unescaped = _unescaped_process_fields(page)
    check("process fields are escaped before render",
          "esc(r.label)" in page and "esc(r.note)" in page and not unescaped,
          ", ".join(unescaped))
    check("process markers are code-set literals, not server text",
          _markers_are_literal(page))
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
