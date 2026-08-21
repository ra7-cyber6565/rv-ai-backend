"""
Chat/LLM resilience test — "Abhi server se baat nahi ho paayi" wale bug ke liye.

INTEL KI REPORT (2026-08-21): website par sawaal bhejne ke baad aakhir mein
"Abhi server se baat nahi ho paayi. Thodi der baad phir bhejo" aa jaata tha.

Asli wajah do thi, dono yahan test hoti hain:

  1. SERVER SIDE — `generate_content()` par koi timeout hi nahi tha. Google ka
     SDK default mein anaadi kaal tak intezaar kar sakta hai, to ek latki hui
     call poori HTTP request ko rok kar rakhti thi aur beech mein browser/gateway
     connection kaat deta tha. Ab har call ki hadd hai (`gemini_model.generate`)
     aur QUICK chat ka poora wall-clock budget bhi (`chat.TOTAL_BUDGET_SECONDS`).

  2. BROWSER SIDE — `web/index.html` ka har fetch `await (await fetch()).json()`
     tha, isliye koi bhi gadbad (502, khaali body, timeout) EK hi line ban jaati
     thi, aur DEEP/MAX ka jawab — jo server par ban CHUKA hota tha — kho jaata
     tha. Ab status alag-alag padha jaata hai aur jawab `/history` se wapas
     laaya jaata hai.

Chalane ka tareeka (poora offline — network nahi, API key nahi):
    python3 tests/test_chat_resilience.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import chat as chat_mod                    # noqa: E402
from research_engine import gemini_model                        # noqa: E402

PASS = 0
FAIL = 0

WEB_PAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "web", "index.html")


def check(name, condition, extra=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f" — {extra}" if extra else ""))


# ── nakli model / SDK ────────────────────────────────────────────────────────
class _Resp:
    def __init__(self, text):
        self.text = text


class _NewSdkModel:
    """Naya SDK — `request_options` leta hai (aur yaad rakhta hai)."""

    def __init__(self, text="jawab", boom=None):
        self.text = text
        self.boom = boom
        self.seen = []

    def generate_content(self, prompt, request_options=None):
        self.seen.append({"prompt": prompt, "request_options": request_options})
        if self.boom is not None:
            raise self.boom
        return _Resp(self.text)


class _OldSdkModel:
    """Purana SDK / nakli test model — sirf prompt leta hai."""

    def __init__(self, text="jawab"):
        self.text = text
        self.calls = 0

    def generate_content(self, prompt):
        self.calls += 1
        return _Resp(self.text)


class _Genai:
    """`genai.GenerativeModel(name)` ka sabse chhota roop."""

    def __init__(self, factory):
        self.factory = factory
        self.built = []

    def GenerativeModel(self, name):            # noqa: N802 - SDK ka naam
        self.built.append(name)
        return self.factory(name)


def main():
    global PASS, FAIL

    print("\n[1] gemini_model.generate — call par waqt ki hadd lagti hai")
    model = _NewSdkModel("theek hai")
    resp = gemini_model.generate(model, "hello")
    check("jawab wahi aata hai", getattr(resp, "text", "") == "theek hai")
    check("prompt waise hi jaata hai", model.seen[0]["prompt"] == "hello")
    opts = model.seen[0]["request_options"] or {}
    check("request_options mein timeout gaya", "timeout" in opts, str(opts))
    check("timeout ek positive number hai",
          isinstance(opts.get("timeout"), int) and opts["timeout"] > 0, str(opts))
    gemini_model.generate(model, "hello", timeout=33)
    check("caller ka timeout izzat paata hai",
          (model.seen[1]["request_options"] or {}).get("timeout") == 33)

    print("\n[2] purana SDK / nakli model — call phir bhi chalti hai")
    old = _OldSdkModel("purana bhi chala")
    resp = gemini_model.generate(old, "hi")
    check("bina request_options wala model bhi jawab deta hai",
          getattr(resp, "text", "") == "purana bhi chala")
    check("usko exactly ek baar call kiya", old.calls == 1, str(old.calls))

    class _KwargsModel:
        def __init__(self):
            self.seen = None

        def generate_content(self, prompt, **kwargs):
            self.seen = kwargs
            return _Resp("kwargs")

    kw = _KwargsModel()
    gemini_model.generate(kw, "hi")
    check("**kwargs wala model bhi timeout paata hai",
          "timeout" in ((kw.seen or {}).get("request_options") or {}))

    print("\n[3] model ki asli galti chhupti nahi hai")
    boom = _NewSdkModel(boom=RuntimeError("429 quota"))
    raised = ""
    try:
        gemini_model.generate(boom, "hi")
    except Exception as exc:            # noqa: BLE001
        raised = f"{type(exc).__name__}: {exc}"
    check("quota/429 wala error upar jaata hai (nigla nahi jaata)",
          "429 quota" in raised, raised)

    bad_kwarg = _NewSdkModel(boom=TypeError("kuch aur hi galat hai"))
    raised = ""
    try:
        gemini_model.generate(bad_kwarg, "hi")
    except TypeError as exc:
        raised = str(exc)
    check("request_options se alag TypeError bhi chhupta nahi",
          "kuch aur hi galat hai" in raised, raised)

    print("\n[4] call_timeout — hadd ke andar hi rehta hai")
    original_env = os.environ.get("GEMINI_CALL_TIMEOUT")
    try:
        os.environ.pop("GEMINI_CALL_TIMEOUT", None)
        default = gemini_model.call_timeout()
        check("default timeout 10..600 ke beech", 10 <= default <= 600, str(default))
        os.environ["GEMINI_CALL_TIMEOUT"] = "1"
        check("bahut chhoti value clamp hoti hai (10)",
              gemini_model.call_timeout() == 10)
        os.environ["GEMINI_CALL_TIMEOUT"] = "99999"
        check("bahut badi value clamp hoti hai (600)",
              gemini_model.call_timeout() == 600)
        os.environ["GEMINI_CALL_TIMEOUT"] = "bakwaas"
        check("kachra value par crash nahi, default milta hai",
              10 <= gemini_model.call_timeout() <= 600)
        os.environ["GEMINI_CALL_TIMEOUT"] = "60"
        check("theek value waise hi chalti hai",
              gemini_model.call_timeout() == 60)
    finally:
        if original_env is None:
            os.environ.pop("GEMINI_CALL_TIMEOUT", None)
        else:
            os.environ["GEMINI_CALL_TIMEOUT"] = original_env

    print("\n[5] QUICK chat — safal jawab bandhe hue waqt ke saath")
    saved_candidates = chat_mod.candidates
    saved_budget = chat_mod.TOTAL_BUDGET_SECONDS
    saved_call = chat_mod.CALL_TIMEOUT_SECONDS
    try:
        made = {}

        def factory(name):
            made[name] = made.get(name) or _NewSdkModel(f"jawab from {name}")
            return made[name]

        chat_mod.candidates = lambda genai: ["m-one", "m-two", "m-three", "m-four", "m-five"]
        genai = _Genai(factory)
        out = chat_mod._one_key_try(genai, "sawaal")
        check("pehle model ka jawab hi le liya", out["text"] == "jawab from m-one",
              out["text"])
        check("sirf ek model try hua", out["tried"] == ["m-one"], str(out["tried"]))
        check("key ko galat nahi thehraya", out["key_dead"] is False)
        opts = made["m-one"].seen[0]["request_options"] or {}
        check("chat ki call par bhi timeout laga", "timeout" in opts, str(opts))
        check("chat ka timeout CALL_TIMEOUT_SECONDS se zyada nahi",
              opts.get("timeout", 10 ** 9) <= chat_mod.CALL_TIMEOUT_SECONDS,
              str(opts))

        print("\n[6] budget khatam hote hi ruk jaata hai (browser ka wait bachta hai)")
        chat_mod.TOTAL_BUDGET_SECONDS = 0

        def slow_factory(name):
            return _NewSdkModel(boom=RuntimeError("dheema model"))

        genai = _Genai(slow_factory)
        out = chat_mod._one_key_try(genai, "sawaal")
        check("budget 0 par sirf ek koshish hui", len(out["tried"]) == 1,
              str(out["tried"]))
        check("phir bhi crash nahi — dict hi laut kar aaya",
              isinstance(out, dict) and out["text"] == "")
        check("aakhri galti yaad rakhi gayi", out["exc"] is not None)
        check("budget khatam hone ko key ki galti nahi maana",
              out["key_dead"] is False)

        print("\n[7] chaar model ki purani hadd waise hi kaayam hai")
        chat_mod.TOTAL_BUDGET_SECONDS = 9999
        genai = _Genai(slow_factory)
        out = chat_mod._one_key_try(genai, "sawaal")
        check("zyada se zyada 4 model try hote hain", len(out["tried"]) == 4,
              str(out["tried"]))

        print("\n[8] quota par backup key ka rasta khulta hai (jaisa pehle tha)")

        def quota_factory(name):
            return _NewSdkModel(boom=RuntimeError("429 RESOURCE_EXHAUSTED quota"))

        genai = _Genai(quota_factory)
        out = chat_mod._one_key_try(genai, "sawaal")
        check("quota par key_dead=True", out["key_dead"] is True)
        check("quota par aage ke model par waqt barbaad nahi kiya",
              len(out["tried"]) == 1, str(out["tried"]))
    finally:
        chat_mod.candidates = saved_candidates
        chat_mod.TOTAL_BUDGET_SECONDS = saved_budget
        chat_mod.CALL_TIMEOUT_SECONDS = saved_call

    print("\n[9] chat ke budget/timeout sach mein bandhe hue hain")
    check("CALL_TIMEOUT_SECONDS 10..300", 10 <= chat_mod.CALL_TIMEOUT_SECONDS <= 300,
          str(chat_mod.CALL_TIMEOUT_SECONDS))
    check("TOTAL_BUDGET_SECONDS 20..600",
          20 <= chat_mod.TOTAL_BUDGET_SECONDS <= 600,
          str(chat_mod.TOTAL_BUDGET_SECONDS))
    check("ek call ka timeout poore budget se bada nahi",
          chat_mod.CALL_TIMEOUT_SECONDS <= chat_mod.TOTAL_BUDGET_SECONDS)

    print("\n[10] website — error par asli wajah + jawab ki recovery")
    page = ""
    try:
        with open(WEB_PAGE, encoding="utf-8") as handle:
            page = handle.read()
    except OSError as exc:
        check("web/index.html padhi ja saki", False, str(exc))
    if page:
        # comment ki lines hata do — purane pattern ka zikr comment mein hai
        # (wahan wo samjhane ke liye likha hai, chalne wale code mein nahi).
        code = "\n".join(line for line in page.splitlines()
                         if not line.strip().startswith("//"))
        check("har fetch ek jagah se jaati hai (postJSON/getJSON)",
              "async function postJSON(" in page and "async function getJSON(" in page)
        check("chalne wale code mein seedha `.json()` kahin nahi",
              ".json()" not in code)
        check("poore page mein sirf do fetch call hain (postJSON + getJSON)",
              code.count("fetch(") == 2, str(code.count("fetch(")))
        check("HTTP status insaani bhaasha mein padha jaata hai",
              "function reasonLine(" in page and "504" in page and "429" in page)
        check("kho gaya jawab history se wapas aata hai",
              "/api/v1/history/" in page and "function recoverAnswer(" in page)
        check("recovery purana jawab nahi uthati (baseline)",
              "baseline" in page and "matchingAnswers(" in page)
        check("recovery nayi research trigger nahi karti (sirf GET)",
              "postJSON(\"/api/v1/deep-research\"" in page
              and page.count("postJSON(\"/api/v1/deep-research\"") == 1)
        check("user ko dobara type nahi karna padta (retry button)",
              "function retryButton(" in page and "Phir bhejo" in page)
        check("QUICK chat ek transient hichki par khud dobara koshish karta hai",
              "await sleep(1500)" in page)
        check("pyaari line hataayi nahi gayi (sirf uske saath sach juda)",
              "Abhi server se baat nahi ho paayi" in page)
        check("recovered jawab ke saath imaandaar note jaata hai",
              "research server par poori ho" in page)
        check("file:// wali samjhaish waise hi hai",
              "file se seedha khola hai" in page)
        check("raw server error text page par nahi dikhta",
              "res.raw" not in page.split("function reasonLine(")[-1][:1200])

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


def test_chat_resilience_all_checks_pass():
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
