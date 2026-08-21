"""
§14 — API accounting aur audit denominators ka permanent taala.

Kyun ye file bani (2026-08-21):
`api_accounting()` mein retry ka hisaab `attempts - calls_used` tha. Us formula
mein model FALLBACK bhi "retry" ban jaata tha:

    model A ek baar gira -> model B par jawab mila
    asli baat: 2 HTTP attempt, 1 model switch, 0 retry
    purana hisaab: retries = 2 - 1 = 1   <-- jhooth

Aur audit ke kai number bina denominator ke chhapte the ("2 source peer-reviewed
hai") — jo 2/3 ho to imaandaar hai, par 2/30 ho to dhokha.

Yahan wahi dono cheezein taale mein band hain. Sab kuch offline: koi network,
koi API key, koi paisa. Chalao:
    python3 tests/test_audit_accounting.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import gemini_model, gemini_reasoning  # noqa: E402
from research_engine.gemini_reasoning import GeminiReasoning  # noqa: E402
from research_engine.model_errors import AUTH, DAILY_QUOTA  # noqa: E402
from research_engine.synthesizer import FinalSynthesizer  # noqa: E402

# Test ko sona nahi hai (asli backoff production ka hai)
gemini_reasoning._BACKOFF_SECONDS = (0.0, 0.0)

PASSED = 0
FAILED = 0


def check(label: str, ok: bool, detail: str = "") -> bool:
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print(f"  [PASS] {label}")
    else:
        FAILED += 1
        print(f"  [FAIL] {label}" + (f" -> {detail}" if detail else ""))
    return bool(ok)


def eq(label: str, got, want) -> bool:
    return check(f"{label} ({want})", got == want, f"mila {got!r}, chahiye {want!r}")


# ── fake model (asli library ko chhue bina) ──────────────────────────────────
class _Resp:
    def __init__(self, text: str):
        self.text = text


class _FakeModel:
    def __init__(self, name: str, script):
        self.name = name
        self.script = list(script)
        self.calls = 0

    def generate_content(self, prompt):              # noqa: ARG002
        self.calls += 1
        item = self.script.pop(0) if self.script else "OK late"
        if isinstance(item, Exception):
            raise item
        return _Resp(item)


def _brain(models, budget: int = 3) -> GeminiReasoning:
    order = list(models.keys())
    fakes = {name: _FakeModel(name, script) for name, script in models.items()}
    gemini_model.forget_dead()                       # test isolation
    brain = GeminiReasoning(budget=budget, model_name=order[0])
    brain._model = fakes[order[0]]
    brain.model = lambda: brain._model
    brain._model_order = lambda: order

    def _build(name):
        brain.model_name = name
        brain._model = fakes[name]
        return fakes[name]

    brain._build = _build
    brain.fakes = fakes
    return brain


_DAILY_TEXT = (
    "ResourceExhausted: 429 You exceeded your current quota. quota_id: "
    "GenerateRequestsPerDayPerProjectPerModel-FreeTier, quota_value: 50"
)


def _rate_limit() -> Exception:
    return RuntimeError("429 ResourceExhausted: quota exceeded, retry soon")


def _daily() -> Exception:
    return RuntimeError(_DAILY_TEXT)


def _auth() -> Exception:
    return RuntimeError("PermissionDenied: 403 API key not valid")


# ── A: pehla model fail -> doosra model safal ────────────────────────────────
def test_model_switch_is_not_a_retry():
    """
    Ye wahi case hai jispar purana formula jhooth bolta tha.

    model-a par 404 (usi model par dobara maarna bekaar hai, seedha agla model),
    model-b par jawab. Asli hisaab: 2 attempt, 1 switch, 0 retry.
    """
    print("\nA. pehla model fail -> doosra safal: switch 1, retry 0")
    brain = _brain({"model-a": [RuntimeError("404 models/model-a is not found")],
                    "model-b": ["doosre model se jawab"]})
    text = brain.generate("p", "synthesis")
    eq("jawab doosre model se aaya", text, "doosre model se jawab")
    acc = brain.api_accounting()
    eq("actual_http_attempts", acc["actual_http_attempts"], 2)
    eq("model_switches", acc["model_switches"], 1)
    eq("same_model_retries", acc["same_model_retries"], 0)
    eq("retries (naya matlab = same-model retry)", acc["retries"], 0)
    eq("successful_calls", acc["successful_calls"], 1)
    eq("failed_http_attempts", acc["failed_http_attempts"], 1)
    eq("logical_reasoning_calls", acc["logical_reasoning_calls"], 1)
    eq("pass se output aaya", acc["passes_with_output"], 1)
    note = brain.usage_note()
    check("usage_note model switch ko 'retry' nahi kehta",
          "shift karna pada" in note and "same-model retry" not in note, note)
    block = FinalSynthesizer._api_accounting_block(acc)
    check("report mein switch aur retry alag-alag line par hain",
          "Same model par dobara koshish (retry): **0**" in block
          and "Doosre model par shift (fallback, retry NAHI): **1**" in block, block)


# ── B: wahi model, thodi der baad dobara -> safal ────────────────────────────
def test_same_model_retry_is_counted_as_retry():
    print("\nB. wahi model temporary fail -> retry -> safal: retry 1, switch 0")
    brain = _brain({"model-a": [_rate_limit(), "retry ke baad jawab"]})
    text = brain.generate("p", "analysis")
    eq("retry ke baad jawab aaya", text, "retry ke baad jawab")
    acc = brain.api_accounting()
    eq("actual_http_attempts", acc["actual_http_attempts"], 2)
    eq("same_model_retries", acc["same_model_retries"], 1)
    eq("model_switches", acc["model_switches"], 0)
    eq("ek hi model try hua", acc["models_tried"], ["model-a"])
    check("attempts ka poora hisaab milta hai (1 pehli koshish + retry + switch)",
          acc["actual_http_attempts"]
          == 1 + acc["same_model_retries"] + acc["model_switches"], str(acc))
    note = brain.usage_note()
    check("usage_note mein same-model retry saaf likha hai",
          "1 same-model retry" in note, note)
    check("aur switch ka jhootha zikr nahi hai", "shift karna pada" not in note, note)


# ── C: HTTP se PEHLE ki failure — attempts nakli nahi badhte ─────────────────
def test_setup_failure_does_not_fake_http_attempts():
    print("\nC. setup/auth failure: HTTP attempt nakli nahi ginte")
    brain = _brain({"model-a": ["kabhi nahi chalega"]})

    def _boom():
        raise RuntimeError("google.generativeai import/config fail")

    brain.model = _boom                              # HTTP se pehle hi gir gaya
    eq("khaali jawab mila", brain.generate("p", "analysis"), "")
    acc = brain.api_accounting()
    eq("actual_http_attempts 0 hi rahe", acc["actual_http_attempts"], 0)
    eq("successful_calls", acc["successful_calls"], 0)
    eq("failed_http_attempts bhi 0 (network par gaye hi nahi)",
       acc["failed_http_attempts"], 0)
    eq("no_api_calls flag", acc["no_api_calls"], True)
    eq("par pass MAANGA gaya tha", acc["logical_reasoning_calls"], 1)
    eq("aur wo khaali laut aaya", acc["passes_empty"], 1)
    eq("khaali pass ka naam bhi likha hai", acc["empty_output_passes"], ["analysis"])
    check("wajah record hui", bool(brain.errors), str(brain.errors))
    block = FinalSynthesizer._api_accounting_block(acc)
    check("report zero-call run par ₹0 saaf likhti hai",
          "ek bhi API call nahi hui" in block and "₹0" in block, block)
    check("aur 3/3 jaisa jhootha 'sab pass ho gaya' nahi dikhata",
          "output sach mein aaya: **0/1**" in block, block)

    # auth failure asli HTTP par ho to attempt ginna SAHI hai (call hui thi)
    brain2 = _brain({"model-a": [_auth()], "model-b": ["kabhi nahi"]})
    eq("auth fail par khaali jawab", brain2.generate("p", "synthesis"), "")
    acc2 = brain2.api_accounting()
    eq("wo ek asli attempt ginti hai", acc2["actual_http_attempts"], 1)
    eq("aage koshish rok di gayi", acc2["stopped_early"], True)
    eq("doosre model par gaye hi nahi", acc2["model_switches"], 0)
    check("failure kind auth hai", AUTH in acc2["failure_kinds"], str(acc2))


# ── D: daily quota wala model agle pass mein dobara nahi ────────────────────
def test_blocked_model_is_not_hit_again_next_pass():
    print("\nD. daily-quota se band model agle logical pass mein dobara nahi")
    brain = _brain({"model-a": [_daily(), "ye kabhi nahi chalna chahiye"],
                    "model-b": ["pehla", "doosra"]}, budget=2)
    eq("pehla pass model-b se aaya", brain.generate("p", "analysis"), "pehla")
    eq("model-a is run ke liye band hai", brain.blocked.get("model-a"), DAILY_QUOTA)
    a_calls_after_first = brain.fakes["model-a"].calls
    eq("model-a par sirf 1 attempt hui thi", a_calls_after_first, 1)
    eq("doosra pass bhi chala", brain.generate("p", "synthesis"), "doosra")
    eq("model-a ko dobara chhua hi nahi", brain.fakes["model-a"].calls,
       a_calls_after_first)
    acc = brain.api_accounting()
    eq("kul HTTP attempts", acc["actual_http_attempts"], 3)
    eq("dono pass se output aaya", acc["passes_with_output"], 2)
    eq("switch sirf pehle pass mein hua", acc["model_switches"], 1)
    eq("koi same-model retry nahi", acc["same_model_retries"], 0)
    check("band model report mein naam se likha hai",
          "model-a" in FinalSynthesizer._api_accounting_block(acc), str(acc))


# ── E: pass maanga vs pass se output aaya (jhoothi 3/3 band) ────────────────
def test_requested_passes_vs_passes_with_output():
    print("\nE. '3/3 pass' ka jhooth: maanga vs mila alag-alag dikhta hai")
    brain = _brain({"model-a": [_daily(), _daily(), _daily()],
                    "model-b": [_daily(), _daily(), _daily()]}, budget=3)
    for label in ("analysis", "critique", "synthesis"):
        eq(f"{label} khaali laut aaya", brain.generate("p", label), "")
    acc = brain.api_accounting()
    eq("teen pass maange gaye", acc["logical_reasoning_calls"], 3)
    eq("teen pass log hue", acc["passes_requested"], 3)
    eq("ek se bhi output nahi aaya", acc["passes_with_output"], 0)
    eq("teeno khaali", acc["passes_empty"], 3)
    eq("naam bhi record hue", acc["empty_output_passes"],
       ["analysis", "critique", "synthesis"])
    note = brain.usage_note()
    check("usage_note ab '3/3 pass ho gaya' jaisa dava nahi karta",
          "0/3 se sach mein output aaya" in note, note)
    block = FinalSynthesizer._api_accounting_block(acc)
    check("report mein bhi 0/3 saaf likha hai",
          "output sach mein aaya: **0/3**" in block, block)
    check("aur ginti ka source bataya gaya hai (billing dashboard nahi)",
          "engine ki apni ginti" in block, block)
    # daily quota par dono model band ho jaate hain, isliye baad ke pass mein
    # HTTP par jaana hi nahi chahiye
    eq("bekaar HTTP attempts nahi hui (2 model, 1-1 attempt)",
       acc["actual_http_attempts"], 2)


# ── F: audit ke denominators ────────────────────────────────────────────────
def test_read_depth_has_denominator():
    print("\nF. 'kitna gehra padha gaya' — har ginti denominator ke saath")
    coverage = {"read_levels": {"full_text": 2, "abstract": 5,
                                "snippet": 3, "metadata": 1}}
    block = FinalSynthesizer._access_block(coverage, None)
    check("kul ginti likhi hai", "kul 11 sources par" in block, block)
    check("full text 2/11", "2/11 source ka POORA text mila" in block, block)
    check("abstract 5/11", "5/11 source ka sirf abstract mila" in block, block)
    check("snippet 3/11", "3/11 source se sirf ek chhota snippet" in block, block)
    check("metadata 1/11", "1/11 source ka sirf title/metadata" in block, block)
    empty = FinalSynthesizer._access_block({}, None)
    check("data hi na ho to seedha bola jaata hai",
          "data available nahi hai" in empty, empty)


def test_quality_counts_have_denominator():
    print("\nG. source quality ki ginti bhi 'kul mein se' ke saath")
    coverage = {"sources_used": 12, "peer_reviewed": 4,
                "strong_methodology_sources": 2, "retracted_sources": 1}
    line = FinalSynthesizer._quality_line(coverage, None)
    check("peer-reviewed 4/12", "4/12 source peer-reviewed hai" in line, line)
    check("strong design 2/12", "2/12 source ka study design mazboot" in line, line)
    check("retraction 1/12", "1/12 source par retraction ka signal" in line, line)
    check("bina denominator wali purani line nahi bachi",
          "- 4 source peer-reviewed hai" not in line, line)


def test_number_checks_have_denominator():
    print("\nH. numbers ki checking mein bhi X/Y")
    verification = {"status": "SOURCE GROUNDED", "checks": [
        {"check": "unit conversion", "passed": False, "detail": "296.15 K vs 23 C"},
        {"check": "arithmetic", "passed": True},
        {"check": "comparison direction", "passed": True},
        {"check": "statistical claim", "passed": None},
    ]}
    text = FinalSynthesizer()._numbers_check(verification)
    check("1/4 mein problem", "1/4 cheez mein problem mili hai" in text, text)
    check("2/4 theek", "2/4 check theek nikle" in text, text)
    check("1/4 check hi nahi ho paayi",
          "1/4 cheez check hi nahi ho paayi" in text, text)


TESTS = (
    test_model_switch_is_not_a_retry,
    test_same_model_retry_is_counted_as_retry,
    test_setup_failure_does_not_fake_http_attempts,
    test_blocked_model_is_not_hit_again_next_pass,
    test_requested_passes_vs_passes_with_output,
    test_read_depth_has_denominator,
    test_quality_counts_have_denominator,
    test_number_checks_have_denominator,
)


def main() -> int:
    print("=" * 70)
    print("§14 — API accounting + audit denominators (poora offline)")
    print("=" * 70)
    for test in TESTS:
        try:
            test()
        except Exception as exc:                     # noqa: BLE001
            global FAILED
            FAILED += 1
            import traceback
            print(f"  [FAIL] {test.__name__} crash kar gaya — {exc!r}")
            traceback.print_exc()
    print(f"\n{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
