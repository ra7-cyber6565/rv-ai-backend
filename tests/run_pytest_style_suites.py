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


def _fixtures(func: Any) -> Tuple[Dict[str, Any], List[Any], str]:
    """Test ko chahiye fixtures banata hai. Teesra return = missing fixture."""
    try:
        params = list(inspect.signature(func).parameters)
    except (TypeError, ValueError):
        return {}, [], ""
    kwargs: Dict[str, Any] = {}
    cleanup: List[Any] = []
    for param in params:
        if param == "tmp_path":
            folder = Path(tempfile.mkdtemp(prefix="silentsuite_"))
            kwargs[param] = folder
            cleanup.append(lambda p=folder: shutil.rmtree(p, ignore_errors=True))
        elif param == "monkeypatch":
            patch = _MonkeyPatch()
            kwargs[param] = patch
            cleanup.append(patch.undo)
        else:
            for done in cleanup:
                done()
            return {}, [], param
    return kwargs, cleanup, ""


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
        for name, func in tests:
            kwargs, cleanup, missing_fixture = _fixtures(func)
            if missing_fixture:
                skipped.append((f"{rel}::{name}",
                                f"fixture shim mein nahi: {missing_fixture}"))
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
                for done in reversed(cleanup):
                    try:
                        done()
                    except Exception:                      # noqa: BLE001
                        pass
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
