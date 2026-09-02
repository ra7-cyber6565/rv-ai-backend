"""Pytest-style test files ko bina pytest ke chalane wala runner (Claude-owned).

Asli dikkat jo isne pakdi (2026-08-22):
    Repo ke bahut se test file sirf `def test_*()` rakhte hain — na `main()`, na
    `if __name__ == "__main__"`. Is sandbox mein pytest install nahi hai, isliye
    `python3 tests/test_foo.py` chup-chaap **exit 0** de deta tha, ek bhi test
    chalaye bina. Matlab "test pass ho gaya" aur "test chala hi nahi" bilkul ek
    jaise dikhte the. Isi chuppi mein 5 asli failure kaafi der tak chhupe rahe
    (§12 ke baad purani heading par tike assert).

Ye runner un files ko import karke unke saare `test_*` callables khud chalata
hai, aur teen haalat alag-alag ginta hai:

    ok    — test chala aur pass hua
    FAIL  — test chala aur assert toota (ya exception aaya)
    SKIP  — module hi import nahi ho paaya kyunki library missing hai
            (fastapi/pytest/httpx/chromadb/google…). Ye sandbox ki kami hai,
            code ki nahi — isliye ise failure nahi ginte, par CHHUPATE bhi
            nahi: naam aur wajah dono print hote hain.

Bahut se test `tmp_path` aur `monkeypatch` fixtures maangte hain. Un dono ka
chhota, imaandaar shim yahin bana hua hai (`_TmpPath`, `_MonkeyPatch`) — isliye
wo test bhi asli mein chalte hain, "fixture nahi mila" keh kar chhoote nahi.
Jo fixture shim mein nahi hai uska test SKIP hota hai, naam ke saath.

Iske alawa file ke andar likhe `@pytest.fixture` bhi asli mein chalte hain —
`autouse=True` wale har test se pehle/baad, aur naam se maange gaye wale
zaroorat par (nested fixture bhi). Ye 2026-08-22 ka asli defect tha: autouse
fixture na chalne se `provider_health` ka global state ek test se doosre mein
leak hota tha aur 5 test JHOOTHE RED aate the. Kya support hai aur kya nahi,
poora hisaab `_FixtureSession` ke paas likha hai; jo shape support nahi hai
(parametrized/async/dynamic-scope fixture) uska test SKIP hota hai — chupaya
nahi jaata. Iska apna test: `tests/test_runner_fixture_support.py`.

Kisi bhi test file ko badalna nahi padta, isliye ChatGPT-owned test files
(`test_final_quality_gate.py`, `test_job_result_progress_snapshot.py`) ko chhua
bhi nahi jaata — wo bas chal jaate hain.

Chalane ka tareeka (repo root = backend/):
    PYTHONPATH=. python3 tests/run_pytest_style_suites.py
    PYTHONPATH=. python3 tests/run_pytest_style_suites.py tests/test_x.py …
"""
from __future__ import annotations

import importlib.util
import inspect
import io
import os
import shutil
import sys
import tempfile
import traceback
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Ye sandbox mein install nahi hain; inka missing hona code ka failure nahi hai.
_ENV_MODULES = (
    "pytest", "fastapi", "starlette", "httpx", "chromadb", "google",
    "sentence_transformers", "torch", "numpy", "requests", "uvicorn",
    "pypdf", "fitz", "bs4", "lxml", "aiohttp", "pydantic",
)


def _candidate_files(argv: List[str]) -> Tuple[List[str], List[str]]:
    """(chalane_layak_files, script_style_files) lautata hai."""
    if argv:
        return [os.path.abspath(path) for path in argv], []
    out: List[str] = []
    script_like: List[str] = []
    for folder in (os.path.join(ROOT, "tests"), ROOT):
        for name in sorted(os.listdir(folder)):
            if not name.startswith("test_") or not name.endswith(".py"):
                continue
            path = os.path.join(folder, name)
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                body = handle.read()
            # Jinke paas apna runner hai unhe ye script nahi chhedti — wo file
            # khud `python3 tests/foo.py` se sach bolti hai.
            if "__main__" in body:
                continue
            # Repo root ke kuch purane "test_" file asli test nahi, demo script
            # hain: unme koi `def test_*` nahi hai aur import karte hi top-level
            # code chal padta hai (search calls tak). Unhe IMPORT bhi nahi
            # karte — warna ek "test run" chupke se network chhoo leta.
            if "def test_" not in body:
                script_like.append(os.path.relpath(path, ROOT))
                continue
            out.append(path)
    return out, script_like


def _import(path: str):
    name = "silentsuite_" + os.path.basename(path)[:-3]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"spec nahi bana: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _env_skip(exc: BaseException) -> str:
    if not isinstance(exc, ModuleNotFoundError):
        return ""
    missing = str(getattr(exc, "name", "") or "").split(".")[0]
    return missing if missing in _ENV_MODULES else ""


class _MonkeyPatch:
    """pytest ke `monkeypatch` fixture ka chhota, poora-undo wala shim.

    Sirf utna hi jitna repo ke test asli mein use karte hain: setattr / delattr
    / setenv / delenv / setitem / delitem / chdir / syspath_prepend. Har change
    stack par record hota hai aur `undo()` ulte kram mein wapas kar deta hai,
    warna ek test ka patch doosre test mein leak ho jaata (aur "pass" jhoota
    ho jaata).
    """

    _MISSING = object()

    def __init__(self) -> None:
        self._undo: List[Any] = []

    # setattr(obj, "name", value)  ya  setattr("pkg.mod.name", value)
    def setattr(self, target: Any, name: Any = _MISSING,
                value: Any = _MISSING, raising: bool = True) -> None:
        if isinstance(target, str):
            value, raising = (name, True) if value is self._MISSING else (value, raising)
            module_path, _, attr = target.rpartition(".")
            obj = self._import_path(module_path)
            name = attr
        else:
            obj, attr = target, name
        old = getattr(obj, name, self._MISSING)
        if old is self._MISSING and raising:
            raise AttributeError(f"{obj!r} par '{name}' nahi hai")
        self._undo.append(("attr", obj, name, old))
        setattr(obj, name, value)

    def delattr(self, target: Any, name: Any = _MISSING,
                raising: bool = True) -> None:
        if isinstance(target, str):
            module_path, _, attr = target.rpartition(".")
            obj, name = self._import_path(module_path), attr
        else:
            obj = target
        old = getattr(obj, name, self._MISSING)
        if old is self._MISSING:
            if raising:
                raise AttributeError(f"{obj!r} par '{name}' nahi hai")
            return
        self._undo.append(("attr", obj, name, old))
        delattr(obj, name)

    def setitem(self, mapping: Any, key: Any, value: Any) -> None:
        old = mapping.get(key, self._MISSING) if hasattr(mapping, "get") \
            else self._MISSING
        self._undo.append(("item", mapping, key, old))
        mapping[key] = value

    def delitem(self, mapping: Any, key: Any, raising: bool = True) -> None:
        if key not in mapping:
            if raising:
                raise KeyError(key)
            return
        self._undo.append(("item", mapping, key, mapping[key]))
        del mapping[key]

    def setenv(self, name: str, value: Any, prepend: str = "") -> None:
        text = str(value)
        if prepend and os.environ.get(name):
            text = text + prepend + os.environ[name]
        self.setitem(os.environ, name, text)

    def delenv(self, name: str, raising: bool = True) -> None:
        self.delitem(os.environ, name, raising=raising)

    def chdir(self, path: Any) -> None:
        self._undo.append(("cwd", None, None, os.getcwd()))
        os.chdir(str(path))

    def syspath_prepend(self, path: Any) -> None:
        self._undo.append(("syspath", None, None, list(sys.path)))
        sys.path.insert(0, str(path))

    @staticmethod
    def _import_path(dotted: str) -> Any:
        """`"utils.reasoning_status.provider_health"` jaisa path resolve karta hai.

        pytest ki tarah step-by-step: pehle import ho sakne wala hissa import
        karo, uske baad har agla hissa pehle `getattr` se dhoondho aur sirf
        zaroorat par submodule import karo. Seedha `import_module(poora_path)`
        karne se un module par patch fail ho jaata hai jo package nahi hain par
        andar attribute rakhte hain (jaise `utils.reasoning_status` ke andar
        import kiya hua `provider_health`).
        """
        import importlib

        parts = dotted.split(".")
        found = importlib.import_module(parts[0])
        used = parts[0]
        for part in parts[1:]:
            used += "." + part
            try:
                found = getattr(found, part)
                continue
            except AttributeError:
                pass
            found = importlib.import_module(used)
        return found

    def undo(self) -> None:
        while self._undo:
            kind, holder, key, old = self._undo.pop()
            if kind == "attr":
                if old is self._MISSING:
                    if hasattr(holder, key):
                        delattr(holder, key)
                else:
                    setattr(holder, key, old)
            elif kind == "item":
                if old is self._MISSING:
                    holder.pop(key, None)
                else:
                    holder[key] = old
            elif kind == "cwd":
                os.chdir(old)
            elif kind == "syspath":
                sys.path[:] = old


# ---------------------------------------------------------------------------
# pytest fixtures (autouse + naam se maange gaye) — bina pytest import kiye
# ---------------------------------------------------------------------------
# Asli defect jo isne pakda (2026-08-22): ye runner `@pytest.fixture` ko
# chalata hi nahi tha. `tests/test_reasoning_router_integration.py` aur
# `tests/test_live_zero_cost_gate.py` ke autouse fixture
# `_isolated_provider_health()` ka kaam hai har test se pehle/baad
# `provider_health.clear()` karna. Wo na chalne se ek test ka fake outage
# (cooldown state) agle test mein leak hota tha aur 5 test JHOOTHE RED aate
# the — asli pytest wahi test pass karta hai (933 passed). Ye "chup-chaap
# green" defect ka ulta hai: chup-chaap RED.
#
# pytest ko import nahi kar sakte (sandbox mein install nahi hai), isliye uska
# shape duck-type karte hain:
#   marker   : func._pytestfixturefunction  (legacy wrapper shape)
#              func._fixture_function_marker (pytest 9 FixtureFunctionDefinition)
#              dono par .scope/.params/.autouse/.name
#   asli fn  : func.__pytest_wrapped__.obj  (legacy wrapper)
#              func._fixture_function       (pytest 9 FixtureFunctionDefinition)
#              func.__wrapped__             (functools.wraps se)
# Jo shape samajh na aaye (parametrized ya async fixture, dynamic scope) uska
# test SKIP hota hai — naam aur wajah ke saath, chupaya nahi jaata.
_FIXTURE_MARKERS = ("_pytestfixturefunction", "_fixture_function_marker")


def _fixture_marker(obj: Any) -> Any:
    """Return fixture metadata for legacy pytest wrappers or pytest 9 definitions.

    Pytest <=8-style wrappers expose ``_pytestfixturefunction``.  Pytest 9's
    ``FixtureFunctionDefinition`` exposes ``_fixture_function_marker`` instead,
    while the underlying callable is available as ``_fixture_function`` (already
    handled by ``_unwrap_fixture`` below).  Keep both shapes: the zero-dependency
    fake fixture probe still exercises the legacy contract.
    """
    for attr in _FIXTURE_MARKERS:
        marker = getattr(obj, attr, None)
        if marker is not None:
            return marker
    return None


class _FixtureError(Exception):
    """Fixture chalane mein asli gadbad — test FAIL hona chahiye."""


class _FixtureUnsupported(Exception):
    """Fixture ka shape shim ke bahar hai — test SKIP hona chahiye."""


def _unwrap_fixture(obj: Any) -> Any:
    """pytest ke wrapper ke andar se asli fixture function nikaalta hai."""
    current = obj
    for _ in range(10):
        wrapped = getattr(current, "__pytest_wrapped__", None)
        inner = getattr(wrapped, "obj", None) if wrapped is not None else None
        if inner is None:
            inner = getattr(current, "_fixture_function", None)
        if inner is None:
            inner = getattr(current, "__wrapped__", None)
        if inner is None or inner is current or not callable(inner):
            return current
        current = inner
    return current


class _FixtureDef:
    """Ek fixture ka poora hisaab (naam, asli function, scope, autouse)."""

    __slots__ = ("name", "func", "scope", "autouse", "needs", "order",
                 "unsupported")

    def __init__(self, name: str, func: Any, scope: str, autouse: bool,
                 order: int, unsupported: str = "") -> None:
        self.name = name
        self.func = func
        self.scope = scope or "function"
        self.autouse = bool(autouse)
        self.order = order
        self.unsupported = unsupported
        try:
            self.needs = list(inspect.signature(func).parameters)
        except (TypeError, ValueError):
            self.needs = []


def _collect_fixtures(module: Any) -> Dict[str, _FixtureDef]:
    """Module ke saare `@pytest.fixture` dhoondho (marker duck-typing se)."""
    found: Dict[str, _FixtureDef] = {}
    for order, (attr, obj) in enumerate(list(vars(module).items())):
        marker = _fixture_marker(obj)
        if marker is None or not callable(obj):
            continue
        name = str(getattr(marker, "name", None) or attr)
        func = _unwrap_fixture(obj)
        scope = getattr(marker, "scope", "function")
        reason = ""
        if getattr(marker, "params", None):
            reason = f"parametrized fixture support nahi hai: {name}"
        elif callable(scope):
            reason = f"dynamic-scope fixture support nahi hai: {name}"
        elif (inspect.iscoroutinefunction(func)
              or inspect.isasyncgenfunction(func)):
            reason = f"async fixture support nahi hai: {name}"
        found[name] = _FixtureDef(
            name, func, "function" if callable(scope) else str(scope or "function"),
            getattr(marker, "autouse", False), order, reason,
        )
    return found


def _start_fixture(fdef: _FixtureDef, kwargs: Dict[str, Any]) -> Tuple[Any, Any]:
    """Fixture chalao. Generator ho to `yield` tak chalao + teardown lauta do."""
    if inspect.isgeneratorfunction(fdef.func):
        gen = fdef.func(**kwargs)
        try:
            value = next(gen)
        except StopIteration:
            raise _FixtureError(f"fixture '{fdef.name}' ne yield hi nahi kiya")

        def finish(handle: Any = gen, label: str = fdef.name) -> None:
            try:
                next(handle)
            except StopIteration:
                return
            raise _FixtureError(f"fixture '{label}' ne ek se zyada yield kiya")

        return value, finish
    return fdef.func(**kwargs), None


class _FixtureSession:
    """Ek test-module ke fixtures: wide-scope cache + teardown stack.

    Note (imaandaar limitation): is repo mein `conftest.py` nahi hai, isliye
    har fixture usi module mein banti hai jahan use hoti hai. Module/session/
    package/class scope ko yahan "ek module ke poore run" tak cache kiya jaata
    hai aur module khatam hone par teardown hota hai — cross-module session
    sharing (jo asli pytest karta hai) ki zaroorat is repo mein padti hi nahi.
    """

    def __init__(self, module: Any) -> None:
        self.defs = _collect_fixtures(module)
        self.wide: Dict[str, Any] = {}
        self.wide_cleanup: List[Any] = []

    def prepare(self, func: Any) -> Tuple[Dict[str, Any], List[Any], str]:
        """(kwargs, cleanup, skip_reason). Autouse pehle, phir naam wale."""
        cleanup: List[Any] = []
        local: Dict[str, Any] = {}
        kwargs: Dict[str, Any] = {}
        try:
            params = list(inspect.signature(func).parameters)
        except (TypeError, ValueError):
            params = []
        autouse = sorted((d for d in self.defs.values() if d.autouse),
                         key=lambda d: d.order)
        try:
            for fdef in autouse:
                self._resolve(fdef.name, local, cleanup, [])
            for param in params:
                kwargs[param] = self._resolve(param, local, cleanup, [])
        except _FixtureUnsupported as exc:
            _drain(cleanup)
            return {}, [], str(exc)
        except BaseException:                                  # noqa: BLE001
            # Setup beech mein toota: jo ban gaya usko saaf karke aage phenk do
            # (warna aadha-bana fixture agle test mein leak karega).
            _drain(cleanup)
            raise
        return kwargs, cleanup, ""


    def _resolve(self, param: str, local: Dict[str, Any],
                 cleanup: List[Any], chain: List[str]) -> Any:
        """Ek fixture (ya shim) banao; nested fixture bhi khud resolve karo."""
        if param in local:
            return local[param]
        if param == "tmp_path":
            folder = Path(tempfile.mkdtemp(prefix="silentsuite_"))
            cleanup.append(lambda p=folder: shutil.rmtree(p, ignore_errors=True))
            local[param] = folder
            return folder
        if param == "monkeypatch":
            patch = _MonkeyPatch()
            cleanup.append(patch.undo)
            local[param] = patch
            return patch
        fdef = self.defs.get(param)
        if fdef is None:
            raise _FixtureUnsupported(f"fixture shim mein nahi: {param}")
        if fdef.unsupported:
            raise _FixtureUnsupported(fdef.unsupported)
        if fdef.scope != "function" and fdef.name in self.wide:
            return self.wide[fdef.name]
        if fdef.name in chain:
            raise _FixtureError("fixture chakkar (circular): "
                                + " -> ".join(chain + [fdef.name]))
        kwargs = {name: self._resolve(name, local, cleanup, chain + [fdef.name])
                  for name in fdef.needs}
        value, finish = _start_fixture(fdef, kwargs)
        if fdef.scope == "function":
            local[fdef.name] = value
            if finish is not None:
                cleanup.append(finish)
        else:
            self.wide[fdef.name] = value
            if finish is not None:
                self.wide_cleanup.append(finish)
        return value

    def close(self) -> List[str]:
        """Module khatam: wide-scope teardown chalao, gadbad ki list lauta do."""
        problems: List[str] = []
        while self.wide_cleanup:
            done = self.wide_cleanup.pop()
            try:
                done()
            except BaseException as exc:                       # noqa: BLE001
                problems.append(f"{type(exc).__name__}: {exc}")
        self.wide.clear()
        return problems


def _drain(cleanup: List[Any]) -> None:
    """Aadhe bane fixtures ko ulte kram mein saaf karo (leak na ho)."""
    while cleanup:
        done = cleanup.pop()
        try:
            done()
        except BaseException:                                  # noqa: BLE001
            pass


def _teardown(cleanup: List[Any]) -> List[str]:
    """Ulte kram mein poora teardown; jo toote unki list lauta do.

    Ek teardown toot jaane par baaki ko chhodte nahi — warna doosra fixture ka
    state agle test mein leak karta rahega (yahi asli bug tha).
    """
    problems: List[str] = []
    while cleanup:
        done = cleanup.pop()
        try:
            done()
        except BaseException as exc:                           # noqa: BLE001
            problems.append(f"{type(exc).__name__}: {exc}")
    return problems


def run(paths: List[str]) -> Tuple[int, int, List[str], List[Tuple[str, str]]]:
    passed = failed = 0
    failures: List[str] = []
    skipped: List[Tuple[str, str]] = []
    for path in paths:
        rel = os.path.relpath(path, ROOT)
        noise = io.StringIO()
        try:
            with redirect_stdout(noise):
                module = _import(path)
        except BaseException as exc:                       # noqa: BLE001
            missing = _env_skip(exc)
            if missing:
                skipped.append((rel, f"module missing: {missing}"))
            else:
                failed += 1
                failures.append(f"{rel} :: IMPORT -> "
                                f"{type(exc).__name__}: {exc}")
            continue
        tests = [(name, obj) for name, obj in sorted(vars(module).items())
                 if name.startswith("test_") and callable(obj)
                 and getattr(obj, "__module__", "") == module.__name__]
        if not tests:
            skipped.append((rel, "koi test_* function nahi mila"))
            continue
        session = _FixtureSession(module)
        for name, func in tests:
            try:
                kwargs, cleanup, missing_fixture = session.prepare(func)
            except BaseException as exc:                       # noqa: BLE001
                missing = _env_skip(exc)
                if missing:
                    skipped.append((f"{rel}::{name}",
                                    f"module missing: {missing}"))
                    continue
                failed += 1
                failures.append(f"{rel}::{name} :: FIXTURE SETUP -> "
                                f"{type(exc).__name__}: {exc}")
                continue
            if missing_fixture:
                skipped.append((f"{rel}::{name}", missing_fixture))
                continue
            try:
                with redirect_stdout(io.StringIO()):
                    func(**kwargs)
            except BaseException as exc:                   # noqa: BLE001, PERF203
                missing = _env_skip(exc)
                if missing:
                    skipped.append((f"{rel}::{name}",
                                    f"module missing: {missing}"))
                    continue
                failed += 1
                detail = str(exc).strip() or traceback.format_exc().strip().splitlines()[-1]
                failures.append(f"{rel}::{name} -> {type(exc).__name__}: {detail}")
            else:
                passed += 1
            finally:
                # Teardown chup-chaap nigla nahi jaata: fixture ka cleanup
                # toota to wo bhi ek asli failure hai (state leak ho sakta hai).
                for problem in _teardown(cleanup):
                    failed += 1
                    failures.append(f"{rel}::{name} :: TEARDOWN -> {problem}")
        for problem in session.close():
            failed += 1
            failures.append(f"{rel} :: MODULE-FIXTURE TEARDOWN -> {problem}")
    return passed, failed, failures, skipped


def main() -> int:
    paths, script_like = _candidate_files(sys.argv[1:])
    print(f"pytest-style suites (bina runner wali files): {len(paths)}")
    passed, failed, failures, skipped = run(paths)
    by_reason: Dict[str, int] = {}
    for _, reason in skipped:
        by_reason[reason] = by_reason.get(reason, 0) + 1
    if script_like:
        print("\nNOT-A-SUITE (koi `def test_` nahi — demo script, import bhi nahi kiya):")
        for rel in script_like:
            print(f"  {rel}")
    if skipped:
        print("\nSKIP (sandbox ki kami — code ka failure nahi):")
        for reason, count in sorted(by_reason.items()):
            print(f"  {count:>3} × {reason}")
    if failures:
        print("\nFAILURES:")
        for line in failures:
            print(f"  [FAIL] {line}")
    print(f"\nPASS: {passed}   FAIL: {failed}   SKIP: {len(skipped)}   "
          f"NOT-A-SUITE: {len(script_like)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
