"""
PC HOST lane ke script ka contract — START_BACKEND_LAN.bat, INSTALL_AUTOSTART.bat,
REMOVE_AUTOSTART.bat, docs/PC_HOST.md.

Yeh suite khud chalti hai (runner `__main__` wali file skip karta hai):

    python tests\\test_pc_host_scripts.py

Kya pakadti hai — wahi teen jhooth jo aise "apna PC hi server" wale lane me
sabse aasani se ghus jaate hain:

  1. LAN par khol dena par user ko yeh na batana ki server par koi login nahi
     hai (jo bhi usi Wi-Fi par hai, wo tumhaare API quota par research chala
     sakta hai),
  2. LAN par bhi `--reload` chhod dena — file badalte hi server restart, aur
     beech ka lamba research khatam,
  3. autostart ka default hi LAN kar dena, ya hataane wala script ek file ke
     bajaye folder/wildcard delete karne lage.

Koi network nahi, koi Windows nahi — sab kuch repo ke andar ke text par.
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_PASS = 0
_FAIL: list[str] = []


def read(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def check(name: str, ok: bool, why: str = "") -> None:
    global _PASS
    if ok:
        _PASS += 1
        print(f"  ok   {name}")
    else:
        _FAIL.append(name)
        print(f"  FAIL {name}" + (f"\n         -> {why}" if why else ""))


def code_only(text: str) -> str:
    """`REM`/`::` comment hata do. Niyam script ke CODE me hona chahiye —
    comment me likh dena kaafi nahi."""
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("REM ") or stripped.startswith("::"):
            continue
        out.append(line)
    return "\n".join(out)


# ------------------------------------------------------- LAN wala start script

def test_lan_script_listens_on_the_network_but_never_reloads() -> None:
    print("\n[1] LAN script: sunta hai sab par, par reload nahi")
    code = code_only(read("START_BACKEND_LAN.bat"))
    check("0.0.0.0 par sunta hai (phone pahunch sake)", "--host 0.0.0.0" in code)
    check("--reload nahi hai (beech ka research na mare)", "--reload" not in code)
    check("uvicorn se main:app chalata hai", "-m uvicorn main:app" in code)
    check("port badla ja sakta hai", "%RV_PORT%" in code)
    check("port ka default 8000 hai", 'set "RV_PORT=8000"' in code)


def test_lan_script_says_out_loud_that_there_is_no_login() -> None:
    print("\n[2] LAN script user ko sach batata hai")
    text = read("START_BACKEND_LAN.bat").lower()
    check("login nahi hai — yeh likha hai", "login" in text and "nahi" in text)
    check("public Wi-Fi par mat chalao — yeh likha hai", "public wi-fi" in text)
    check("firewall me Private par allow — yeh likha hai",
          "firewall" in text and "private" in text)
    # Warning sirf comment me nahi, chalte waqt screen par bhi dikhe.
    shown = code_only(read("START_BACKEND_LAN.bat")).lower()
    check("warning screen par bhi print hoti hai (sirf comment me nahi)",
          "[dhyan]" in shown)


def test_lan_script_keeps_the_data_drive_safety() -> None:
    print("\n[3] Heavy data chupke se C: par nahi")
    code = code_only(read("START_BACKEND_LAN.bat"))
    check("INFINITY_DATA_ROOT ka hisaab hai", "INFINITY_DATA_ROOT" in code)
    check("drive maujood na ho to start hi nahi hota",
          'if not exist "%DATA_DRIVE%\\"' in code and "exit /b 1" in code)
    check("venv ka python pehle try hota hai", "venv\\Scripts\\python.exe" in code)


def test_local_script_stays_local_only() -> None:
    print("\n[4] Purana local script waisa hi rehta hai")
    code = code_only(read("START_BACKEND.bat"))
    check("START_BACKEND.bat sirf 127.0.0.1 par sunta hai",
          "--host 127.0.0.1" in code and "0.0.0.0" not in code,
          "local lane ko LAN par kholna chup-chaap risk badha dega")


# --------------------------------------------------------------- autostart

def test_autostart_default_is_the_safe_mode() -> None:
    print("\n[5] Autostart ka default safe hai")
    code = code_only(read("INSTALL_AUTOSTART.bat"))
    check('default mode "local" hai (LAN nahi)', 'set "MODE=local"' in code)
    check("local mode local script chalata hai",
          'set "TARGET=START_BACKEND.bat"' in code)
    check("lan mode LAN script chalata hai",
          'set "TARGET=START_BACKEND_LAN.bat"' in code)
    check("local/lan ke alawa kuch nahi chalta",
          "Mode sirf" in read("INSTALL_AUTOSTART.bat") and "exit /b 1" in code)
    check("lan chuna to risk dobara batata hai",
          "DHYAN" in read("INSTALL_AUTOSTART.bat"))


def test_autostart_needs_no_admin_and_no_system_surgery() -> None:
    print("\n[6] Autostart me koi system surgery nahi")
    code = code_only(read("INSTALL_AUTOSTART.bat")).lower()
    for banned in ("schtasks", "reg add", "reg.exe", "sc create", "nssm",
                   "runas", "powershell"):
        check(f"{banned} use nahi hota", banned not in code)
    check("sirf Startup folder me ek file rakhta hai",
          "start menu\\programs\\startup" in code)
    check("file ka naam fix hai (hataana aasaan)", "rv_ai_backend.cmd" in code)


def test_remove_script_deletes_exactly_one_file() -> None:
    print("\n[7] Hataane wala script sirf ek file hataata hai")
    text = read("REMOVE_AUTOSTART.bat")
    code = code_only(text).lower()
    check("ek hi del command hai", code.count("del ") == 1, code)
    check("del sirf HOOK par lagta hai", 'del "%hook%"' in code)
    for banned in ("/s", "/q", "rd ", "rmdir", "*", "del %", "erase"):
        check(f"khatarnak pattern nahi: {banned!r}", banned not in code)
    check("na mile to bhi shanti se nikalta hai",
          'if not exist "%HOOK%"' in text and "exit /b 0" in text)
    check("project ka data safe rehta hai — yeh likha hai",
          "delete nahi hoti" in text)


# ------------------------------------------------------------------ common

def test_scripts_are_plain_ascii_and_hold_no_secret() -> None:
    print("\n[8] ASCII aur koi secret nahi")
    # Naam dhoondhna kaafi nahi — `tokens=2` aur "login/password nahi hai" jaise
    # imaandaar shabd bhi usi naam ke hote hain. Dekhna yeh hai ki kahin kisi
    # secret ko VALUE di ja rahi hai ya nahi.
    assigned = re.compile(
        r"(?i)(api[_-]?key|apikey|token|secret|password|passwd|credential)"
        r"\s*[:=]\s*\S"
    )
    keyish = re.compile(r"(?i)(AIza[0-9A-Za-z_\-]{10,}|bearer\s+\S|"
                        r"authorization\s*[:=])")
    for name in ("START_BACKEND_LAN.bat", "INSTALL_AUTOSTART.bat",
                 "REMOVE_AUTOSTART.bat"):
        raw = open(os.path.join(ROOT, name), "rb").read()
        bad = [b for b in raw if b > 127]
        check(f"{name} pura ASCII hai (cmd ka ANSI trap)", not bad,
              f"{len(bad)} byte 127 se upar")
        text = raw.decode("ascii", "replace")
        hit = assigned.search(text)
        check(f"{name} me kisi secret ko value nahi di gayi",
              hit is None, hit.group(0) if hit else "")
        hit2 = keyish.search(text)
        check(f"{name} me key/bearer jaisa literal nahi",
              hit2 is None, hit2.group(0) if hit2 else "")
    for name in ("START_BACKEND_LAN.bat", "INSTALL_AUTOSTART.bat"):
        code = code_only(read(name)).lower()
        check(f"{name} chupke se pip install nahi karta", "pip install" not in code)


def test_doc_states_the_limit_and_the_safer_lanes() -> None:
    print("\n[9] Doc sach bolta hai")
    doc = read("docs", "PC_HOST.md")
    low = doc.lower()
    check("doc kehta hai login/password nahi hai",
          "koi login/password nahi" in low)
    check("doc public Wi-Fi par mana karta hai",
          "hostel" in low and "mat chalao" in low)
    check("doc PC band = server band, yeh maanta hai", "pc band ho to" in low)
    # Safe raste sirf neeche ki table me hona kaafi nahi — jahan "mat chalao"
    # likha hai, wahin par aage ka raasta bhi bataana chahiye.
    warn = low.split("saaf baat", 1)[-1].split("\n## ", 1)[0]
    check("usi warning ke saath safe raste bhi (Tailscale + Tunnel)",
          "tailscale" in warn and "tunnel" in warn,
          "warning section me safe lane ka naam nahi mila")
    check("doc firewall ka Private wala kadam batata hai",
          "private networks" in low)
    check("doc me tino script ka naam hai",
          "START_BACKEND_LAN.bat" in doc and "INSTALL_AUTOSTART.bat" in doc
          and "REMOVE_AUTOSTART.bat" in doc)
    check("doc app ke http-only-local niyam par imaandaar hai",
          "network_security_config.xml" in doc)


def main() -> int:
    print("PC HOST lane contract\n" + "=" * 46)
    for fn in (
        test_lan_script_listens_on_the_network_but_never_reloads,
        test_lan_script_says_out_loud_that_there_is_no_login,
        test_lan_script_keeps_the_data_drive_safety,
        test_local_script_stays_local_only,
        test_autostart_default_is_the_safe_mode,
        test_autostart_needs_no_admin_and_no_system_surgery,
        test_remove_script_deletes_exactly_one_file,
        test_scripts_are_plain_ascii_and_hold_no_secret,
        test_doc_states_the_limit_and_the_safer_lanes,
    ):
        fn()
    total = _PASS + len(_FAIL)
    print("\n" + "=" * 46)
    print(f"{_PASS}/{total} theek, {len(_FAIL)} fail")
    for name in _FAIL:
        print(f"  - {name}")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
