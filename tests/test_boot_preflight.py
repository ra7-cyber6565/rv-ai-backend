"""`scripts/boot_preflight.py` ke tests (Claude-owned).

Kyun ye file bani (2026-08-22):
    Railway ka `502 Bad Gateway` sirf itna batata hai ki process ne `$PORT` bind
    nahi kiya. Asli wajah `import main` ke teen fail-closed guard me se koi ek
    hoti hai. Preflight script un teenon ko naam deti hai - par ek diagnostic
    script jo galat jawab de, us se bura kuch nahi. Isliye har gate ka green
    aur red dono side test hota hai, aur ye bhi test hota hai ki output me
    kisi credential ki VALUE nahi jaati (sirf NAAM).

Ye file jaan-boojh kar pytest ke bina chalti hai (plain assert), taaki
`tests/run_pytest_style_suites.py` bhi ise chala sake.

Ek defect jo isi file ne paida kiya tha (2026-08-23, band):
    Do test asli `load_dotenv()` chalate hain. pytest poori suite EK process
    mein chalata hai, isliye `.env` ki `GEMINI_API_KEY` +
    `GEMINI_ZERO_COST_CONFIRMED=true` process ke `os.environ` mein baith jaati
    thi. `tests/test_provider_health.py` aur `tests/test_reasoning_router.py`
    apne import ke waqt wahi key `pop` karke "offline" hone ka bharosa karte
    hain - par unka import pehle hota hai aur ye test baad mein chalta hai, to
    pop bekaar ho jaata tha. Nateeja: router ka
    `ResilientReasoning._gemini_allowed()` True ban jaata tha aur wo offline
    test asli Gemini primary call maar dete the -> 6 test fail (Windows par,
    jahan `google-generativeai` install hai; sandbox mein SDK na hone se ye
    chhupa raha). Isliye neeche har dotenv-wala test `_restored_env()` ke andar
    chalta hai aur baad mein saabit karta hai ki ek bhi naam leak nahi hua.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from contextlib import contextmanager

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _load():
    path = os.path.join(ROOT, "scripts", "boot_preflight.py")
    spec = importlib.util.spec_from_file_location("rv_boot_preflight", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BP = _load()
FAKE_KEY = "AIzaSyRVTESTFAKEKEYVALUE0123456789xyz"


def _root(folder: str) -> str:
    return os.path.join(folder, "runtime_data")


@contextmanager
def _restored_env():
    """`os.environ` ka snapshot lo aur block ke baad hu-ba-hu wapas rakho.

    Sirf naye naam hataana kaafi nahi - `load_dotenv()` maujood naam ki value
    bhi badal sakta hai, isliye value-wise wapasi hoti hai.
    """
    before = dict(os.environ)
    try:
        yield before
    finally:
        for name in [n for n in os.environ if n not in before]:
            del os.environ[name]
        for name, value in before.items():
            if os.environ.get(name) != value:
                os.environ[name] = value


def test_gemini_key_without_confirmation_is_named_as_the_boot_killer():
    with tempfile.TemporaryDirectory() as folder:
        env = {"PORT": "8080", "INFINITY_DATA_ROOT": _root(folder),
               "GEMINI_API_KEY": FAKE_KEY}
        result = BP.check_zero_cost(env)
    assert result.level == BP.FATAL, result.detail
    assert "GEMINI_ZERO_COST_CONFIRMED" in result.detail + result.fix
    # NAAM chhapa, VALUE nahi.
    assert "GEMINI_API_KEY" in result.detail
    assert FAKE_KEY not in result.detail + result.fix


def test_same_config_with_confirmation_goes_green():
    """Ye check red ho SAKTA hai to hi uske PASS ka matlab hai."""
    with tempfile.TemporaryDirectory() as folder:
        env = {"PORT": "8080", "INFINITY_DATA_ROOT": _root(folder),
               "GEMINI_API_KEY": FAKE_KEY, "GEMINI_ZERO_COST_CONFIRMED": "true"}
        result = BP.check_zero_cost(env)
    assert result.level == BP.OK, result.detail
    assert FAKE_KEY not in result.detail


def test_numbered_backup_key_alone_is_also_caught():
    env = {"GEMINI_API_KEY_2": FAKE_KEY}
    result = BP.check_zero_cost(env)
    assert result.level == BP.FATAL, result.detail
    assert "GEMINI_API_KEY_2" in result.detail
    assert FAKE_KEY not in result.detail


def test_paid_provider_key_is_blocked_by_name():
    result = BP.check_zero_cost({"OPENAI_API_KEY": "sk-fake-value-0123456789"})
    assert result.level == BP.FATAL, result.detail
    assert "OPENAI_API_KEY" in result.detail
    assert "sk-fake-value-0123456789" not in result.detail


def test_zero_cost_off_is_reported_but_not_fatal():
    env = {"ZERO_COST_ONLY": "false", "GEMINI_API_KEY": FAKE_KEY}
    result = BP.check_zero_cost(env)
    assert result.level == BP.OK, result.detail
    assert "zero_cost_enabled=false" in result.detail


def test_cors_wildcard_and_schemeless_are_fatal_good_origin_is_ok():
    wild = BP.check_cors({"CORS_ALLOWED_ORIGINS": "*"})
    assert wild.level == BP.FATAL, wild.detail
    assert "CORS_ALLOWED_ORIGINS" in wild.fix

    bare = BP.check_cors({"CORS_ALLOWED_ORIGINS": "web-production-0dd45.up.railway.app"})
    assert bare.level == BP.FATAL, bare.detail
    assert "http" in bare.detail

    good = BP.check_cors({"CORS_ALLOWED_ORIGINS": "https://web-production-0dd45.up.railway.app"})
    assert good.level == BP.OK, good.detail
    assert "1 origin" in good.detail

    empty = BP.check_cors({})
    assert empty.level == BP.OK, empty.detail


def test_unwritable_storage_root_is_fatal_with_a_fix():
    with tempfile.TemporaryDirectory() as folder:
        blocker = os.path.join(folder, "blocker")
        with open(blocker, "w", encoding="utf-8") as handle:
            handle.write("main file, folder nahi")
        result = BP.check_storage({"INFINITY_DATA_ROOT": os.path.join(blocker, "sub")})
    assert result.level == BP.FATAL, result.detail
    assert "INFINITY_DATA_ROOT" in result.fix


def test_writable_storage_root_is_ok():
    with tempfile.TemporaryDirectory() as folder:
        result = BP.check_storage({"INFINITY_DATA_ROOT": _root(folder)})
        assert result.level == BP.OK, result.detail
        assert os.path.isdir(os.path.join(_root(folder), "uploads"))


def test_windows_path_on_linux_warns_instead_of_silently_passing():
    if os.name == "nt":
        return  # Windows par 'D:\\...' bilkul sahi path hai - ye trap sirf Linux ka hai
    result = BP.check_storage({"INFINITY_DATA_ROOT": "D:\\InfinityResearchAI"})
    assert result.level == BP.WARN, result.detail
    assert "Linux" in result.detail + result.fix
    assert not os.path.exists("D:\\InfinityResearchAI")  # probe ne junk folder nahi banaya


def test_port_states():
    assert BP.check_port({}).level == BP.WARN
    assert BP.check_port({"PORT": "abc"}).level == BP.FATAL
    assert BP.check_port({"PORT": "8080"}).level == BP.OK


def test_scrub_removes_env_secret_values_and_keyish_strings():
    env = {"GEMINI_API_KEY": FAKE_KEY, "X_PROJECT_TOKEN": "tok_abcdef123456"}
    text = "boot toota: key=%s token=%s" % (FAKE_KEY, "tok_abcdef123456")
    out = BP.scrub(text, env)
    assert FAKE_KEY not in out
    assert "tok_abcdef123456" not in out
    assert "<REDACTED:GEMINI_API_KEY>" in out
    # AIza-jaisa pattern env me na ho to bhi hatta hai.
    assert "AIza" not in BP.scrub("leak AIzaSyOTHERKEYVALUE0123456789", {})


def test_scrub_reads_env_fresh_each_call():
    """Cache karne se nayi key chhap jaati - isliye har call par env padho."""
    first = BP.scrub("value=old_secret_value", {"A_KEY": "old_secret_value"})
    assert "old_secret_value" not in first
    second = BP.scrub("value=new_secret_value", {"A_KEY": "new_secret_value"})
    assert "new_secret_value" not in second


def test_full_report_never_prints_a_key_value_and_names_the_fatal_gate():
    with tempfile.TemporaryDirectory() as folder:
        env = {"PORT": "8080", "INFINITY_DATA_ROOT": _root(folder),
               "GEMINI_API_KEY": FAKE_KEY}
        results = BP.run(env=env)
        text = BP.render(results)
    assert FAKE_KEY not in text
    assert "zero-cost guard" in text
    assert "boot MAREGA" in text
    assert BP.exit_code(results) == 1


def test_clean_env_report_says_boot_will_work():
    with tempfile.TemporaryDirectory() as folder:
        env = {"PORT": "8080", "INFINITY_DATA_ROOT": _root(folder)}
        results = BP.run(env=env)
        text = BP.render(results)
    assert BP.exit_code(results) == 0
    assert "boot chalega" in text
    assert "MAREGA" not in text


def test_cause_chain_reaches_the_innermost_reason():
    try:
        try:
            raise OSError("disk read-only")
        except OSError as inner:
            raise RuntimeError("storage root unavailable") from inner
    except RuntimeError as exc:
        chain = BP._cause_chain(exc)
    assert chain[0].startswith("RuntimeError")
    assert any("disk read-only" in item for item in chain)


def test_explicit_env_never_gets_polluted_by_local_dotenv():
    """Test-env do to `.env` load nahi hona chahiye, warna jawab badal jaata hai."""
    before = dict(os.environ)
    with tempfile.TemporaryDirectory() as folder, _restored_env():
        env = {"PORT": "8080", "INFINITY_DATA_ROOT": _root(folder),
               "GEMINI_API_KEY": FAKE_KEY}
        results = BP.run(env=env, use_dotenv=True)
    assert len(results) == len(BP.GATES)
    assert BP.exit_code(results) == 1  # .env ka CONFIRMED=true isko chura nahi sakta
    assert dict(os.environ) == before, "test ne process env badal diya"


def test_dotenv_step_is_never_startup_fatal():
    before = dict(os.environ)
    with _restored_env():
        result = BP.load_dotenv_like_main()
        assert result.level in (BP.OK, BP.WARN), result.detail
        assert not result.fatal
    assert dict(os.environ) == before, "test ne process env badal diya"


def test_dotenv_test_does_not_leak_env_into_the_rest_of_the_suite():
    """Ye guard hi 2026-08-23 ke 6 pytest failures ki wajah pakadta hai.

    Upar wale do test asli `load_dotenv()` chalate hain. Wo `.env` ki
    `GEMINI_API_KEY`/`GEMINI_ZERO_COST_CONFIRMED` process env mein chhod dein to
    `tests/test_reasoning_router.py` aur `tests/test_provider_health.py` ke
    offline test asli Gemini call maarne lagte hain. Yahan hum wahi do test
    seedha chala kar naapte hain ki ek bhi naam bacha to nahi.
    """
    watched = ("GEMINI_API_KEY", "GEMINI_API_KEYS", "GEMINI_API_KEY_2",
               "GEMINI_ZERO_COST_CONFIRMED", "GEMINI_MODEL", "TAVILY_API_KEY",
               "ZERO_COST_ONLY")
    before = {name: os.environ.get(name) for name in watched}
    test_dotenv_step_is_never_startup_fatal()
    test_explicit_env_never_gets_polluted_by_local_dotenv()
    after = {name: os.environ.get(name) for name in watched}
    leaked = sorted(name for name in watched if before[name] != after[name])
    assert not leaked, (
        "dotenv test ne env leak kiya (naam only, value nahi): %s - isse "
        "offline router test live provider call maar dete hain" % (leaked,)
    )
