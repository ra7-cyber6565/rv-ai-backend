"""`tests/run_pytest_style_suites.py` ke fixture support ke tests (Claude-owned).

Kyun ye file bani (2026-08-22):
    Runner `@pytest.fixture(autouse=True)` ko chalata hi nahi tha. Isse
    `tests/test_reasoning_router_integration.py` ke 5 test JHOOTHE RED aaye —
    `provider_health` ka cooldown state ek test se doosre mein leak ho raha
    tha, jabki asli pytest wahi test pass karta hai. "Chup-chaap green" runner
    jitna khatarnaak hai, "chup-chaap red" runner bhi utna hi — dono baar
    number jhooth bolte hain.

Yahan har test ek chhota nakli test-module likhta hai (tempfile mein, repo ke
andar kuch nahi banta) aur runner se chalata hai. Sandbox mein pytest install
nahi hai, isliye zaroorat padne par pytest 8.3.4 ka bilkul wahi attribute shape
nakli banaya jaata hai:
    marker  : func._pytestfixturefunction  (.scope/.params/.autouse/.ids/.name)
    asli fn : func.__pytest_wrapped__.obj
Nakli wrapper ko seedha call karne par wo RuntimeError phenkta hai (asli pytest
bhi `fail()` karta hai) — matlab agar runner unwrap karna bhool jaaye to test
turant red ho jaayega. Windows par asli pytest maujood hota hai, to wahan asli
`pytest.fixture` hi use hota hai.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
import textwrap
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _load_runner():
    """Runner ko file path se load karo (tests/ package nahi hai)."""
    path = os.path.join(ROOT, "tests", "run_pytest_style_suites.py")
    spec = importlib.util.spec_from_file_location("rv_runner_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = _load_runner()


def _fake_pytest() -> types.ModuleType:
    """pytest 8.3.4 ke fixture decorator ka hu-ba-hu shape (bina pytest)."""
    module = types.ModuleType("pytest")

    class _Marker:
        def __init__(self, scope="function", params=None, autouse=False,
                     ids=None, name=None):
            self.scope = scope
            self.params = params
            self.autouse = autouse
            self.ids = ids
            self.name = name

        def __call__(self, function):
            def wrapper(*args, **kwargs):
                # Asli pytest bhi seedha call par fail() karta hai. Isliye agar
                # runner unwrap na kare, test turant red ho jaayega.
                raise RuntimeError(
                    "Fixture ko seedha call nahi kar sakte: " + function.__name__
                )

            wrapper.__name__ = function.__name__
            wrapper.__doc__ = function.__doc__
            wrapper.__module__ = function.__module__
            # NOTE: jaan-boojh kar functools.wraps NAHI — taaki `__wrapped__`
            # ka aasaan raasta na mile aur `__pytest_wrapped__` hi test ho.
            wrapper.__pytest_wrapped__ = types.SimpleNamespace(obj=function)
            wrapper._pytestfixturefunction = self
            return wrapper

    def fixture(fixture_function=None, *, scope="function", params=None,
                autouse=False, ids=None, name=None):
        marker = _Marker(scope, params, autouse, ids, name)
        if fixture_function is not None:
            return marker(fixture_function)
        return marker

    module.fixture = fixture
    return module


def _install_pytest_shim():
    """pytest na ho to nakli shim daalo; hatane wala callable lauta do.

    Shim ko case ke turant baad hatana ZAROORI hai. Warna isi process mein
    aage chalne wali `tests/test_security_config.py` jaisi files ko lagta hai
    "pytest mil gaya" aur wo `pytest.raises` par toot jaati hain — matlab meri
    probe hi doosre test ka result jhootha kar deti (asli sandbox mein wo files
    imaandaari se SKIP hoti hain).
    """
    if "pytest" in sys.modules:
        return lambda: None
    try:
        import pytest  # noqa: F401
    except ModuleNotFoundError:
        sys.modules["pytest"] = _fake_pytest()

        def _remove() -> None:
            sys.modules.pop("pytest", None)

        return _remove
    return lambda: None


_COUNTER = [0]


class _Case:
    """Ek nakli test-module ka result: counts + module (state dekhne ke liye)."""

    def __init__(self, passed, failed, failures, skipped, module):
        self.passed = passed
        self.failed = failed
        self.failures = failures
        self.skipped = skipped
        self.module = module

    @property
    def reasons(self):
        return [reason for _, reason in self.skipped]

    def joined(self):
        return " | ".join(list(self.failures) + self.reasons)


def _run_case(source: str) -> _Case:
    """Nakli test-module tempfile mein likho aur runner se chalao."""
    remove_shim = _install_pytest_shim()
    _COUNTER[0] += 1
    name = "probe_%d_%d" % (os.getpid(), _COUNTER[0])
    folder = tempfile.mkdtemp(prefix="rv_fixture_probe_")
    path = os.path.join(folder, name + ".py")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(textwrap.dedent(source).lstrip("\n"))
    try:
        passed, failed, failures, skipped = RUNNER.run([path])
    finally:
        module = sys.modules.pop("silentsuite_" + name, None)
        shutil.rmtree(folder, ignore_errors=True)
        remove_shim()
    return _Case(passed, failed, failures, skipped, module)


_AUTOUSE_CASE = """
    import pytest

    STATE = {"dirty": 0, "setups": 0, "teardowns": 0}

    @pytest.fixture(autouse=True)
    def _isolated():
        STATE["setups"] += 1
        STATE["dirty"] = 0
        yield
        STATE["teardowns"] += 1
        STATE["dirty"] = 0

    def test_a_leaves_state_dirty():
        assert STATE["dirty"] == 0
        STATE["dirty"] = 1

    def test_b_needs_clean_state():
        assert STATE["dirty"] == 0
"""


def test_autouse_fixture_runs_setup_and_teardown_per_test():
    """Yahi asli bug tha: autouse fixture na chalne se state leak hota tha."""
    case = _run_case(_AUTOUSE_CASE)
    assert case.failed == 0, case.joined()
    assert case.passed == 2, case.joined()
    assert case.module is not None
    assert case.module.STATE["setups"] == 2
    assert case.module.STATE["teardowns"] == 2


def test_mutation_without_fixture_support_goes_red_again():
    """Mutation test: fixture support hata do to leak wala test FAIL ho.

    Iske bina ye pura check jhootha hoga - ek aisa assert jo kabhi red hi na
    ho sake, wo kuch bhi verify nahi karta.
    """
    original = RUNNER._collect_fixtures
    RUNNER._collect_fixtures = lambda module: {}
    try:
        case = _run_case(_AUTOUSE_CASE)
    finally:
        RUNNER._collect_fixtures = original
    assert case.failed == 1, case.joined()
    assert case.passed == 1, case.joined()
    assert any("test_b_needs_clean_state" in line for line in case.failures), \
        case.joined()
    # Aur confirm: support wapas aane par wahi case phir green hota hai.
    again = _run_case(_AUTOUSE_CASE)
    assert again.failed == 0, again.joined()


def test_named_and_nested_fixtures_resolve_with_shims():
    case = _run_case("""
        import pytest

        SEEN = {}

        @pytest.fixture
        def base_value():
            return 41

        @pytest.fixture
        def bumped(base_value, tmp_path):
            SEEN["tmp_exists"] = tmp_path.is_dir()
            yield base_value + 1

        def test_uses_nested(bumped):
            assert bumped == 42
            assert SEEN["tmp_exists"] is True
    """)
    assert case.failed == 0, case.joined()
    assert case.passed == 1, case.joined()


def test_module_scope_fixture_built_once_and_torn_down_at_end():
    case = _run_case("""
        import pytest

        COUNT = {"setup": 0, "teardown": 0}

        @pytest.fixture(scope="module")
        def shared():
            COUNT["setup"] += 1
            yield {"id": COUNT["setup"]}
            COUNT["teardown"] += 1

        def test_first(shared):
            assert shared["id"] == 1

        def test_second(shared):
            assert shared["id"] == 1
    """)
    assert case.failed == 0, case.joined()
    assert case.passed == 2, case.joined()
    assert case.module.COUNT == {"setup": 1, "teardown": 1}, case.module.COUNT


def test_fixture_name_override_is_honoured():
    case = _run_case("""
        import pytest

        @pytest.fixture(name="alias")
        def _hidden_factory():
            return "aa gaya"

        def test_alias(alias):
            assert alias == "aa gaya"
    """)
    assert case.failed == 0, case.joined()
    assert case.passed == 1, case.joined()


def test_unsupported_fixture_shapes_skip_loudly_not_silently_pass():
    """Jo shape shim ke bahar hai wo SKIP ho - par naam/wajah ke saath."""
    case = _run_case("""
        import pytest

        @pytest.fixture(params=[1, 2])
        def many(request):
            return request.param

        @pytest.fixture
        async def slow():
            return 1

        def test_needs_params(many):
            assert many

        def test_needs_async(slow):
            assert slow
    """)
    assert case.passed == 0, case.joined()
    assert case.failed == 0, case.joined()
    assert len(case.skipped) == 2, case.joined()
    blob = " ".join(case.reasons)
    assert "parametrized" in blob, blob
    assert "async" in blob, blob


def test_fixture_setup_error_is_a_failure_not_a_silent_pass():
    case = _run_case("""
        import pytest

        @pytest.fixture(autouse=True)
        def _broken():
            raise RuntimeError("setup toot gaya")

        def test_should_not_be_counted_green():
            assert True
    """)
    assert case.passed == 0, case.joined()
    assert case.failed == 1, case.joined()
    assert "FIXTURE SETUP" in case.joined(), case.joined()


def test_circular_fixture_is_reported_not_hung():
    case = _run_case("""
        import pytest

        @pytest.fixture
        def left(right):
            return right

        @pytest.fixture
        def right(left):
            return left

        def test_circular(left):
            assert left
    """)
    assert case.failed == 1, case.joined()
    assert "circular" in case.joined(), case.joined()


def test_teardown_runs_even_when_the_test_fails():
    case = _run_case("""
        import pytest

        MARKS = []

        @pytest.fixture(autouse=True)
        def _always():
            MARKS.append("setup")
            yield
            MARKS.append("teardown")

        def test_fails_on_purpose():
            assert False, "jaan-boojh kar fail"
    """)
    assert case.failed == 1, case.joined()
    assert case.module.MARKS == ["setup", "teardown"], case.module.MARKS


def test_broken_teardown_is_counted_not_swallowed():
    case = _run_case("""
        import pytest

        @pytest.fixture(autouse=True)
        def _bad_teardown():
            yield
            raise RuntimeError("teardown toot gaya")

        def test_body_is_fine():
            assert True
    """)
    assert case.passed == 1, case.joined()
    assert case.failed == 1, case.joined()
    assert "TEARDOWN" in case.joined(), case.joined()


def test_probe_leaves_no_fake_pytest_behind():
    """Meri probe doosre test files ka result nahi badal sakti.

    Ek dafa yahi galti ho chuki hai: nakli `pytest` sys.modules mein chhod
    diya to `tests/test_security_config.py` ko lagta hai pytest mil gaya aur
    wo `pytest.raises` par jhootha FAIL de deti hai.
    """
    before = sys.modules.get("pytest")
    case = _run_case("""
        def test_trivial():
            assert True
    """)
    assert case.passed == 1, case.joined()
    assert sys.modules.get("pytest") is before
