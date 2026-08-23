"""Boot preflight: 502 ke peeche ki asli wajah ko NAAM do.

Kyun ye file bani (2026-08-22):
    Railway par `/api/v1/chat/diag` ne bare `502 Bad Gateway` diya. 502 ka matlab
    hai process ne `$PORT` bind hi nahi kiya - yaani `import main` ke waqt hi
    exception aayi. Client ko us waqt koi wajah nahi dikhti. `main.py` import hote
    hi teen guard chalte hain aur teenon jaan-boojh kar fail-closed hain
    (yahi sahi bhi hai - inhe kamzor karna mana hai):

        1. utils.storage_paths.configure_process_storage()   (main.py ~line 12)
        2. utils.zero_cost_guard.enforce_zero_cost_config()  (main.py ~line 37)
        3. utils.security_config.allowed_cors_origins()      (main.py ~line 38)

    Ye script wahi teen guard alag-alag chalati hai aur har ek ka natija
    plain-language wajah + fix ke saath chhapti hai. Guard ka FAISLA ye script
    kabhi nahi badalti - sirf uska naam leti hai.

Chalane ka tarika (repo ke `backend` folder se):
    python scripts/boot_preflight.py                # sirf config gates (sasta)
    python scripts/boot_preflight.py --import-app   # asli `import main` bhi karo
    python scripts/boot_preflight.py --json         # machine-readable

Exit code: 0 = boot chalega, 1 = startup-fatal problem mili.

SECRET SAFETY: kisi credential ki VALUE nahi chhapti - sirf variable ka NAAM aur
"set/not set". Poore output par ek redaction pass bhi chalta hai (env ki secret
values + AIza-jaisa pattern), taaki traceback ke through bhi key leak na ho.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OK = "OK"
WARN = "WARN"
FATAL = "FATAL"

_SECRET_NAME_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE)
_KEYISH_RE = re.compile(r"AIza[0-9A-Za-z_\-]{10,}")
_WINDOWS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
_MIN_REDACT_LEN = 6


def scrub(text: object, env: Mapping[str, str] | None = None) -> str:
    """Env ki secret values aur key-jaise pattern hata do.

    Har call par env dobara padha jaata hai (cache nahi), warna test/monkeypatch
    ke baad purani list se scrub hota rahega aur ek nayi key chhap jaayegi.
    """
    source = env if env is not None else os.environ
    out = str(text)
    pairs = []
    for name, value in source.items():
        if not _SECRET_NAME_RE.search(str(name)):
            continue
        raw = str(value or "").strip()
        if len(raw) >= _MIN_REDACT_LEN:
            pairs.append((raw, "<REDACTED:%s>" % name))
    pairs.sort(key=lambda item: len(item[0]), reverse=True)
    for secret, label in pairs:
        out = out.replace(secret, label)
    return _KEYISH_RE.sub("<REDACTED-KEYISH>", out)


class Result:
    """Ek gate ka natija: level + wajah + fix (sab plain language me)."""

    __slots__ = ("name", "level", "detail", "fix")

    def __init__(self, name: str, level: str, detail: str, fix: str = "") -> None:
        self.name = name
        self.level = level
        self.detail = detail
        self.fix = fix

    @property
    def fatal(self) -> bool:
        return self.level == FATAL

    def to_dict(self) -> dict[str, str]:
        return {"gate": self.name, "level": self.level,
                "detail": self.detail, "fix": self.fix}

    def lines(self) -> list[str]:
        out = ["[%s] %s: %s" % (self.level, self.name, self.detail)]
        if self.fix:
            out.append("       FIX -> %s" % self.fix)
        return out


def check_storage(env: Mapping[str, str] | None = None) -> Result:
    """main.py line ~12: configure_process_storage() -> ensure_layout() ka gate."""
    source = env if env is not None else os.environ
    from utils import storage_paths

    raw = (str(source.get("INFINITY_DATA_ROOT", "") or "").strip()
           or str(source.get("INFINITY_WORK_ROOT", "") or "").strip())
    if raw and _WINDOWS_PATH_RE.match(raw) and os.name != "nt":
        # Linux par 'D:\X' ek legal FILE NAME hai - mkdir chal jaayega aur guard
        # pass ho jaayega, par data chup-chaap ek junk folder me chala jaayega.
        return Result(
            "storage root", WARN,
            "INFINITY_DATA_ROOT/INFINITY_WORK_ROOT me Windows-style path hai "
            "(%s) par process Linux par chal raha hai" % raw,
            "Railway (Linux) me is variable ko hatao ya Linux path do "
            "(jaise /app/runtime_data ya ek mounted volume ka path)",
        )

    try:
        layout = storage_paths.ensure_layout(source)
    except BaseException as exc:  # noqa: BLE001 - boot yahin marta hai
        return Result(
            "storage root", FATAL,
            scrub("%s: %s" % (type(exc).__name__, exc), source),
            "Us root ko writable banao ya INFINITY_DATA_ROOT hata do "
            "(default = <repo>/runtime_data). Guard jaan-boojh kar koi "
            "fallback drive use nahi karta.",
        )
    root, explicit = storage_paths.configured_root(source)
    return Result(
        "storage root", OK,
        "writable hai (%s, explicitly set = %s)" % (layout.get("root", root),
                                                    str(bool(explicit)).lower()),
    )


def _gemini_var_names(guard: Any) -> list[str]:
    """Guard ki hi list use karo (drift na ho), fallback ke saath."""
    names = list(getattr(guard, "_GEMINI_SINGLE_VARS", ("GEMINI_API_KEY",)))
    names += list(getattr(guard, "_GEMINI_LIST_VARS", ("GEMINI_API_KEYS",)))
    names += ["GEMINI_API_KEY_%d" % i for i in range(2, 10)]
    names += ["GEMINI_API_KEY%d" % i for i in range(2, 10)]
    return names


def check_zero_cost(env: Mapping[str, str] | None = None) -> Result:
    """main.py line ~37: enforce_zero_cost_config() ka gate.

    Sirf NAAM chhapte hain. Value kahin nahi jaati.
    """
    source = env if env is not None else os.environ
    from utils import zero_cost_guard as guard

    status = guard.inspect_zero_cost_config(source)
    present = [name for name in _gemini_var_names(guard)
               if str(source.get(name, "") or "").strip()]
    confirmed = str(source.get("GEMINI_ZERO_COST_CONFIRMED", "") or "").strip().lower()
    where = "set Gemini vars (naam only): %s | GEMINI_ZERO_COST_CONFIRMED=%s | " \
            "ZERO_COST_ONLY=%s" % (
                ", ".join(present) if present else "(koi nahi)",
                confirmed if confirmed else "(not set)",
                str(source.get("ZERO_COST_ONLY", "(not set -> default true)")),
            )
    if status.blocked_keys:
        return Result(
            "zero-cost guard", FATAL,
            "boot yahin rukega. Blocked: %s. %s" % ("; ".join(status.blocked_keys), where),
            "Do hi imaandaar raaste hain: (a) us Google project me billing "
            "band hai ye khud verify karke GEMINI_ZERO_COST_CONFIRMED=true set "
            "karo, ya (b) key hata do. Guard ko kamzor karna mana hai.",
        )
    return Result("zero-cost guard", OK,
                  "pass (zero_cost_enabled=%s). %s" % (str(status.enabled).lower(), where))


def check_cors(env: Mapping[str, str] | None = None) -> Result:
    """main.py line ~38: allowed_cors_origins() ka gate."""
    source = env if env is not None else os.environ
    from utils import security_config

    raw = str(source.get("CORS_ALLOWED_ORIGINS", "") or "")
    try:
        origins = security_config.allowed_cors_origins(source)
    except BaseException as exc:  # noqa: BLE001 - boot yahin marta hai
        return Result(
            "cors origins", FATAL,
            scrub("%s: %s" % (type(exc).__name__, exc), source),
            "CORS_ALLOWED_ORIGINS me har origin poora likho "
            "(https://host), '*' allowed nahi. Website same-origin par chalti "
            "hai, isliye is variable ko khaali/hataya bhi ja sakta hai.",
        )
    return Result("cors origins", OK,
                  "%d origin allowed (raw %s)" % (len(origins),
                                                  "khaali" if not raw.strip() else "set"))


def check_port(env: Mapping[str, str] | None = None) -> Result:
    """Procfile: uvicorn --port $PORT. PORT na ho to uvicorn hi start nahi hoga."""
    source = env if env is not None else os.environ
    raw = str(source.get("PORT", "") or "").strip()
    if not raw:
        return Result("PORT", WARN, "PORT set nahi hai",
                      "Railway khud PORT deta hai; local par "
                      "`uvicorn main:app --port 8000` chalao.")
    if not raw.isdigit():
        return Result("PORT", FATAL, "PORT number nahi hai: %r" % raw,
                      "PORT me sirf ginti honi chahiye.")
    return Result("PORT", OK, "PORT=%s" % raw)


def _cause_chain(exc: BaseException) -> list[str]:
    """Exception ki poori chain (cause/context) - sabse andar wali wajah tak."""
    chain: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen and len(chain) < 8:
        seen.add(id(current))
        chain.append("%s: %s" % (type(current).__name__, current))
        current = current.__cause__ or current.__context__
    return chain


def _app_frame(exc: BaseException) -> str:
    """Repo ke andar ka aakhri frame - yaani asli file:line jahan boot mara."""
    try:
        frames = traceback.extract_tb(exc.__traceback__)
    except Exception:  # noqa: BLE001
        return ""
    label = ""
    for frame in frames:
        try:
            path = Path(frame.filename).resolve()
            path.relative_to(ROOT)
        except Exception:  # noqa: BLE001
            continue
        label = "%s:%s in %s" % (path.relative_to(ROOT).as_posix(),
                                 frame.lineno, frame.name)
    return label


def check_import_app(env: Mapping[str, str] | None = None) -> Result:
    """Aakhri sach: kya `import main` chalta hai? Railway wahi karta hai."""
    source = env if env is not None else os.environ
    try:
        import main  # noqa: F401
    except BaseException as exc:  # noqa: BLE001 - 502 ki asli wajah yahi hoti hai
        chain = " <- ".join(_cause_chain(exc))
        frame = _app_frame(exc)
        return Result(
            "import main", FATAL,
            scrub("%s%s" % (chain, (" | jahan tuta: " + frame) if frame else ""), source),
            "Upar ke gate dekho - jo FATAL hai wahi wajah hai. Sab OK hone par "
            "bhi ye FATAL rahe to wajah is chain me nayi hai.",
        )
    return Result("import main", OK,
                  "app object ban gaya - is env par boot nahi marega")


GATES = (check_storage, check_zero_cost, check_cors, check_port)


def load_dotenv_like_main() -> Result:
    """main.py line ~7 pehle `load_dotenv()` karta hai - preflight bhi kare.

    Warna local (Windows) par ulta jawab milta hai: `.env` me
    GEMINI_ZERO_COST_CONFIRMED=true hai, par preflight process-env dekh kar
    "FATAL" keh deti. Railway par `.env` nahi hota, isliye wahan koi asar nahi.
    """
    try:
        from dotenv import load_dotenv
    except Exception:  # noqa: BLE001
        return Result(".env", WARN, "python-dotenv nahi mila - sirf process env dekha",
                      "Railway par .env hota bhi nahi, wahan ye theek hai.")
    env_file = ROOT / ".env"
    if not env_file.is_file():
        return Result(".env", OK, "koi .env file nahi (Railway par aisa hi hota hai)")
    load_dotenv(str(env_file))
    return Result(".env", OK,
                  "load kar liya (jaise main.py karta hai) - naam only, value nahi")


def run(import_app: bool = False,
        env: Mapping[str, str] | None = None,
        use_dotenv: bool = False) -> list[Result]:
    results: list[Result] = []
    if use_dotenv and env is None:
        results.append(load_dotenv_like_main())
    results.extend(gate(env) for gate in GATES)
    if import_app:
        results.append(check_import_app(env))
    return results


def exit_code(results: list[Result]) -> int:
    return 1 if any(item.fatal for item in results) else 0


def render(results: list[Result]) -> str:
    lines = ["RV AI boot preflight (koi key value print nahi hoti)", ""]
    for item in results:
        lines.extend(item.lines())
    fatal = [item.name for item in results if item.fatal]
    warn = [item.name for item in results if item.level == WARN]
    lines.append("")
    if fatal:
        lines.append("NATIJA: boot MAREGA. Startup-fatal gate: %s" % ", ".join(fatal))
        lines.append("Railway par iska matlab bare 502 hota hai - process $PORT "
                     "bind hi nahi karta.")
    else:
        lines.append("NATIJA: is env par boot chalega.")
    if warn:
        lines.append("Dhyaan dene wale (fatal nahi): %s" % ", ".join(warn))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RV AI boot preflight")
    parser.add_argument("--import-app", action="store_true",
                        help="asli `import main` bhi karo (sabse pakka check)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--no-dotenv", action="store_true",
                        help="local .env ko na padho (sirf process env dekho)")
    args = parser.parse_args(argv)

    results = run(import_app=args.import_app, use_dotenv=not args.no_dotenv)
    if args.json:
        print(json.dumps({"gates": [item.to_dict() for item in results],
                          "boot_will_fail": bool(exit_code(results))}, indent=2))
    else:
        print(render(results))
    return exit_code(results)


if __name__ == "__main__":
    raise SystemExit(main())
