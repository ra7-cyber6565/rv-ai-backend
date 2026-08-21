"""
§8 — "quota khatam ho gaya" ka permanent taala.

Kyun ye file bani (intel, 2026-08-21):
    "gimini ko call krte h to quta khatam ho jaata h isliye usme aesa becup bhi
     hona chahiye, app ruke nhi, app me koi eror na aaye ... iska quta khatam ho
     gya, ye kaam nhi kiya, iss wajah se jawab thoda week rah gya."

Teen cheezein yahan taale mein band hain:
    A. BACKUP FREE KEY — ek key ka quota marne par doosri free key par shift, aur
       us shift ko "retry" mat gino (§14 ka hisaab jhootha ho jaata).
    B. KEY KI VALUE KABHI BAHAR NAHI — note/audit/usage_note mein sirf
       "free key #2" jaisa label.
    C. QUOTA POORI TARAH MARNE PAR BHI JAWAB POORA — engine ka apna offline
       reasoning saare section bharta hai, aur wahi jawab dobara chalane par
       shabd-ba-shabd wahi aata hai.
    D. QUICK chat kabhi dead-end nahi — key na ho / quota mar jaaye to bhi jawab.

Sab offline: koi network, koi API key, koi paisa. Chalao:
    python3 tests/test_quota_backup.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import gemini_model, gemini_reasoning  # noqa: E402
from research_engine.gemini_reasoning import GeminiReasoning  # noqa: E402
from research_engine.key_pool import KeyPool, load_keys  # noqa: E402
from research_engine.local_reasoning import compose, quick_answer  # noqa: E402
from research_engine.models import (EvidencePack, SourceRecord,  # noqa: E402
                                    SourceType)
from research_engine.synthesizer import SECTION_TITLES  # noqa: E402

gemini_reasoning._BACKOFF_SECONDS = (0.0, 0.0)   # test ko sona nahi hai

PASSED = 0
FAILED = 0

# asli key jaisa dikhne wala DUMMY text — kabhi network par nahi jaata
_K1 = "AIzaTEST_KEY_ONE_do_not_use"
_K2 = "AIzaTEST_KEY_TWO_do_not_use"
_K3 = "AIzaTEST_KEY_THREE_do_not_use"


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


_DAILY_TEXT = (
    "ResourceExhausted: 429 You exceeded your current quota. quota_id: "
    "GenerateRequestsPerDayPerProject-FreeTier, quota_value: 50"
)


def _daily() -> Exception:
    return RuntimeError(_DAILY_TEXT)


def _auth() -> Exception:
    return RuntimeError("PermissionDenied: 403 API key not valid")


def _brain_with_keys(keys, per_key_scripts, budget: int = 3) -> GeminiReasoning:
    """
    Ek brain jisme key rotation asli hai, par network nahi.

    `per_key_scripts` = list of dict(model_name -> script). Key #1 ke liye
    pehla dict, key #2 ke liye doosra, etc. Key badalne par model naye script
    par reset ho jaate hain — bilkul waise jaise asli zindagi mein doosre
    project ka quota taaza hota hai.
    """
    gemini_model.forget_dead()
    brain = GeminiReasoning(budget=budget)
    brain.keys = KeyPool(list(keys))
    state = {"i": 0}

    def _fakes():
        scripts = per_key_scripts[min(state["i"], len(per_key_scripts) - 1)]
        return {name: _FakeModel(name, s) for name, s in scripts.items()}

    box = {"fakes": _fakes()}
    order = list(per_key_scripts[0].keys())
    brain.model_name = order[0]
    brain._model = box["fakes"][order[0]]
    brain.model = lambda: brain._model
    brain._model_order = lambda: list(box["fakes"].keys())

    def _build(name):
        brain.model_name = name
        brain._model = box["fakes"][name]
        return box["fakes"][name]

    brain._build = _build

    real_switch = brain._switch_key

    def _switch(tag, reason="quota"):
        before = brain.keys.index
        ok = real_switch(tag, reason)
        if ok and brain.keys.index != before:
            state["i"] = brain.keys.index
            box["fakes"] = _fakes()
            names = list(box["fakes"].keys())
            brain.model_name = names[0]
            brain._model = box["fakes"][names[0]]
        return ok

    brain._switch_key = _switch
    brain.box = box
    return brain


# ── evidence pack (deterministic, offline) ───────────────────────────────────
def _pack() -> EvidencePack:
    q = "Kya intermittent fasting type 2 diabetes mein madad karta hai?"
    pack = EvidencePack(question=q)
    pack.sources = [
        SourceRecord(
            title="Randomized trial of time-restricted eating",
            url="https://journals.example.org/trial-1", source_id="S1",
            snippet=("In this randomized trial HbA1c dropped by 0.6% because "
                     "insulin sensitivity improved. However the sample was "
                     "small (n=40) and follow-up was only 12 weeks."),
            source_type=SourceType.PAPER, peer_reviewed=True, is_primary=True,
            read_level="full_text", full_text_chars=9000, combined_score=0.91,
            doi="10.1000/trial1"),
        SourceRecord(
            title="Meta-analysis of 23 fasting trials",
            url="https://meta.example.net/ma-23", source_id="S2",
            snippet=("Across 23 trials intermittent fasting improved insulin "
                     "sensitivity in type 2 diabetes patients. The effect was "
                     "modest and inconsistent across study designs."),
            source_type=SourceType.PAPER, peer_reviewed=True,
            read_level="abstract", combined_score=0.74, doi="10.1000/ma23"),
        SourceRecord(
            title="Intermittent fasting (encyclopedia entry)",
            url="https://en.wikipedia.org/wiki/Intermittent_fasting",
            source_id="S3",
            snippet="Intermittent fasting is an eating pattern that cycles "
                    "between periods of fasting and eating.",
            source_type=SourceType.ENCYCLOPEDIA, read_level="snippet",
            combined_score=0.35),
    ]
    return pack


_PLAN = {"sub_questions": [
    "Long-term mortality par kya asar hai?",
    "Kaun se marizon mein risk zyada hai?",
]}

_RAW_TOKENS = ("429", "resourceexhausted", "traceback", "protobuf",
               "quota_id", "generaterequestsperday", "permissiondenied",
               "invalidargument", "<class", "exception")


# ── A: env se saari free key uthti hain, duplicate hat jaate hain ────────────
def test_load_keys_from_env():
    print("\nA. env se free key ki kataar")
    env = {"GEMINI_API_KEY": _K1, "GEMINI_API_KEY_2": _K2,
           "GEMINI_API_KEY_BACKUP": _K1,          # jaan-boojh kar duplicate
           "GEMINI_API_KEYS": f"{_K3}, {_K2}"}
    keys = load_keys(env)
    eq("teen unique key mili", len(keys), 3)
    eq("pehli key wahi purani (behaviour na badle)", keys[0], _K1)
    check("duplicate ek hi baar aayi", keys.count(_K1) == 1, str(len(keys)))

    pool = KeyPool(keys)
    eq("backup maujood hai", pool.has_backup(), True)
    eq("label #1", pool.label(), "free key #1")
    pool.advance("quota")
    eq("shift ke baad label #2", pool.label(), "free key #2")
    eq("switches gina gaya", pool.switches, 1)
    note = pool.note()
    check("note mein koi key value nahi", all(k not in note for k in keys), note)

    single = KeyPool([_K1])
    eq("ek hi key: backup nahi (purana behaviour)", single.has_backup(), False)
    eq("khaali pool: has_key False", KeyPool([]).has_key(), False)
    check("khaali pool ka label imaandaar",
          "nahi" in KeyPool([]).label(), KeyPool([]).label())


# ── B: key #1 ka DIN ka quota khatam -> key #2 par jawab ─────────────────────
def test_daily_quota_switches_to_backup_key():
    print("\nB. key #1 ka din ka quota khatam -> backup free key par jawab")
    brain = _brain_with_keys(
        [_K1, _K2],
        [{"model-a": [_daily()], "model-b": [_daily()]},      # key #1 poori mari
         {"model-a": ["backup key se poora jawab"]}],         # key #2 taaza
    )
    text = brain.generate("p", "synthesis")
    eq("jawab backup key se aaya", text, "backup key se poora jawab")
    eq("key switch 1", brain.key_switches, 1)
    eq("ab free key #2 chal rahi hai", brain.keys.label(), "free key #2")
    eq("pass se output aaya", brain.passes_with_output(), 1)
    eq("naye key par purane block bhula diye", brain.blocked, {})

    acc = brain.api_accounting()
    eq("accounting: key_switches", acc["key_switches"], 1)
    eq("accounting: keys_available", acc["keys_available"], 2)
    eq("accounting: active_key label", acc["active_key"], "free key #2")
    # §14 — key badalna RETRY nahi hai
    eq("same_model_retries 0 (key badalna retry nahi)",
       acc["same_model_retries"], 0)
    eq("retries 0", acc["retries"], 0)
    check("identity: attempts == (1+key_switches) + retries + model_switches",
          acc["actual_http_attempts"] == (1 + acc["key_switches"]
                                         + acc["same_model_retries"]
                                         + acc["model_switches"]), str(acc))
    note = brain.usage_note()
    check("usage_note key shift ko 'retry' nahi kehta",
          "backup free key par shift" in note and "retry" not in note.split(
              "backup free key")[0].split("same-model")[-1], note)
    check("usage_note mein key ki value nahi",
          _K1 not in note and _K2 not in note, note)


# ── C: auth fail bhi key-level hai -> doosri key try hoti hai ────────────────
def test_auth_failure_tries_backup_key():
    print("\nC. key galat/permission fail -> backup key try hoti hai")
    brain = _brain_with_keys(
        [_K1, _K2],
        [{"model-a": [_auth()]},
         {"model-a": ["doosri key theek thi"]}],
    )
    text = brain.generate("p", "analysis")
    eq("doosri key se jawab mila", text, "doosri key thik thi".replace(
        "thik", "theek"))
    eq("key switch 1", brain.key_switches, 1)
    eq("stopped flag nayi key par saaf ho gaya", brain.stopped, False)


# ── D: ek hi key ho to bilkul purana behaviour ───────────────────────────────
def test_single_key_behaviour_unchanged():
    print("\nD. ek hi free key: purana behaviour bilkul same")
    brain = _brain_with_keys([_K1], [{"model-a": [_daily()],
                                      "model-b": [_daily()]}])
    text = brain.generate("p", "critique")
    eq("jawab nahi mila (quota poori mari)", text, "")
    eq("koi key switch nahi", brain.key_switches, 0)
    acc = brain.api_accounting()
    eq("keys_available 1", acc["keys_available"], 1)
    check("purani identity bhi tikti hai (key_switches=0)",
          acc["actual_http_attempts"] == 1 + acc["same_model_retries"]
          + acc["model_switches"], str(acc))
    check("crash nahi hua, engine chalta raha", brain.stopped is False)


# ── E: saari key mar gayi -> imaandaar note, par app zinda ──────────────────
def test_all_keys_dead_is_honest():
    print("\nE. saari free key mar gayi -> imaandaar note, koi crash nahi")
    brain = _brain_with_keys(
        [_K1, _K2, _K3],
        [{"model-a": [_daily()]}, {"model-a": [_daily()]},
         {"model-a": [_daily()]}],
    )
    text = brain.generate("p", "synthesis")
    eq("jawab khaali", text, "")
    eq("do baar key badli", brain.key_switches, 2)
    joined = " ".join(brain.notes)
    check("note batata hai ki saari free key khatam ho gayi",
          "saari 3 free key" in joined, joined)
    check("notes mein koi key value nahi",
          all(k not in joined for k in (_K1, _K2, _K3)), joined)
    acc = brain.api_accounting()
    check("accounting mein bhi key value nahi",
          all(k not in str(acc) for k in (_K1, _K2, _K3)), str(acc))
    eq("empty pass imaandaari se gina gaya", brain.passes_with_output(), 0)


# ── F: offline reasoning se JAWAB POORA — saare section bharte hain ─────────
def test_offline_answer_fills_every_section():
    print("\nF. quota poori mari, phir bhi jawab ke saare section bhare")
    pack = _pack()
    answer = compose(pack.question, pack, _PLAN)
    want = [f"## {SECTION_TITLES[i]}" for i in (0, 1, 2, 3, 4, 7, 8)]
    for title in want:
        check(f"section maujood: {title}", title in answer, answer[:200])
    # heading ke neeche kuch to likha ho — khaali heading hi purani shikayat thi
    for title in want:
        body = answer.split(title, 1)[1].split("\n## ", 1)[0].strip()
        check(f"section khaali nahi: {title}", len(body) > 40, repr(body[:60]))
    check("jawab chhota-mota nahi hai", len(answer) > 1200, str(len(answer)))
    check("har source cite hua", all(f"[{i}]" in answer
                                    for i in ("S1", "S2", "S3")), answer[:200])


# ── G: koi jhootha label nahi, koi raw error nahi ───────────────────────────
def test_offline_answer_is_honest():
    print("\nG. offline jawab imaandaar hai: na [ESTABLISHED], na raw error")
    answer = compose(_pack().question, _pack(), _PLAN)
    check("[ESTABLISHED] ka dava nahi", "[ESTABLISHED]" not in answer, answer[:200])
    check("[SOURCE-REPORTED] label lagta hai", "[SOURCE-REPORTED]" in answer)
    check("engine ke apne jod ko [INFERENCE] kaha gaya", "[INFERENCE]" in answer)
    low = answer.lower()
    for token in _RAW_TOKENS:
        check(f"raw token nahi: {token}", token not in low, token)
    check("saaf likha hai ki AI model nahi chala",
          "AI" in answer or "ai reasoning" in low, answer[-300:])


# ── H: deterministic — wahi pack, wahi jawab (shabd-ba-shabd) ──────────────
def test_offline_answer_is_deterministic():
    print("\nH. wahi pack -> wahi jawab, shabd-ba-shabd")
    a = compose(_pack().question, _pack(), _PLAN)
    b = compose(_pack().question, _pack(), _PLAN)
    check("do run byte-identical", a == b, "farak aa gaya")
    empty = compose("Kuch bhi", EvidencePack(question="Kuch bhi"), None)
    check("source hi na ho to bhi crash nahi", len(empty) > 50, empty[:80])
    check("khaali pack par bhi jhootha dava nahi",
          "[ESTABLISHED]" not in empty, empty[:120])


# ── I: bhasha mirror — Hindi sawal, Hindi jawab ka lehja ───────────────────
def test_language_mirror():
    print("\nI. bhasha mirror: script ke hisaab se jawab")
    pack = _pack()
    hindi = compose("क्या उपवास मधुमेह में मदद करता है?", pack, _PLAN)
    eng = compose("Does fasting help diabetes?", pack, _PLAN)
    check("Hindi sawal par Devanagari lines aayi",
          any("ऀ" <= ch <= "ॿ" for ch in hindi), hindi[:120])
    check("English sawal par English lead",
          "Here is what the sources" in eng or "sources themselves" in eng,
          eng[:200])
    check("dono mein heading canonical hi rahi",
          f"## {SECTION_TITLES[0]}" in hindi and f"## {SECTION_TITLES[0]}" in eng)


# ── J: QUICK chat kabhi dead-end nahi ──────────────────────────────────────
def test_quick_backup_never_dead_ends():
    print("\nJ. QUICK: quota mare to bhi jawab (free sources / imaandaar line)")
    pack = _pack()

    def _fake_search(query, limit=3):                # noqa: ARG001
        return pack.sources[:2]

    out = quick_answer("fasting kya karta hai", searcher=_fake_search)
    eq("ok True (UI par 'Failed' nahi)", out["ok"], True)
    eq("mode QUICK", out["mode"], "QUICK")
    eq("backup free sources se bana", out["backup"], "free-sources")
    check("jawab khaali nahi", len(out["answer"]) > 80, out["answer"][:80])
    check("source ka naam jawab mein hai",
          "Randomized trial" in out["answer"], out["answer"][:200])
    low = out["answer"].lower()
    for token in _RAW_TOKENS:
        check(f"QUICK jawab mein raw token nahi: {token}", token not in low, token)

    # search band ho (RV_QUICK_BACKUP_SEARCH=0) — phir bhi imaandaar jawab
    old = os.environ.get("RV_QUICK_BACKUP_SEARCH")
    os.environ["RV_QUICK_BACKUP_SEARCH"] = "0"
    try:
        off = quick_answer("kuch bhi poochho")
    finally:
        if old is None:
            os.environ.pop("RV_QUICK_BACKUP_SEARCH", None)
        else:
            os.environ["RV_QUICK_BACKUP_SEARCH"] = old
    eq("search band hone par bhi ok True", off["ok"], True)
    eq("backup = honest-message", off["backup"], "honest-message")
    check("jawab mein wajah likhi hai", len(off["answer"]) > 40, off["answer"])
    check("quota ki line quota wale case mein hai",
          "free limit" in off["answer"] or "limit" in off["answer"], off["answer"])

    # key hi set na ho to "quota khatam" kehna jhooth hai — sach likha jaata hai
    old2 = os.environ.get("RV_QUICK_BACKUP_SEARCH")
    os.environ["RV_QUICK_BACKUP_SEARCH"] = "0"
    try:
        nokey = quick_answer("kuch bhi", cause="no-key")
    finally:
        if old2 is None:
            os.environ.pop("RV_QUICK_BACKUP_SEARCH", None)
        else:
            os.environ["RV_QUICK_BACKUP_SEARCH"] = old2
    eq("no-key case mein bhi ok True", nokey["ok"], True)
    check("no-key case mein 'quota khatam' ka jhooth nahi",
          "free limit khatam" not in nokey["answer"], nokey["answer"])
    check("no-key case mein asli wajah likhi hai",
          "key" in nokey["answer"], nokey["answer"])

    # searcher hi phat jaaye to bhi jawab aaye
    def _boom(query, limit=3):                       # noqa: ARG001
        raise RuntimeError("network gone")

    safe = quick_answer("test", searcher=_boom)
    eq("searcher crash hone par bhi ok True", safe["ok"], True)
    check("crash ka raw text user ko nahi dikhta",
          "network gone" not in safe["answer"], safe["answer"][:120])


def main() -> int:
    print("=" * 70)
    print("§8 — QUOTA BACKUP (free key rotation + offline reasoning)")
    print("=" * 70)
    test_load_keys_from_env()
    test_daily_quota_switches_to_backup_key()
    test_auth_failure_tries_backup_key()
    test_single_key_behaviour_unchanged()
    test_all_keys_dead_is_honest()
    test_offline_answer_fills_every_section()
    test_offline_answer_is_honest()
    test_offline_answer_is_deterministic()
    test_language_mirror()
    test_quick_backup_never_dead_ends()
    print("\n" + "=" * 70)
    print(f"{PASSED} passed, {FAILED} failed")
    print("=" * 70)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
