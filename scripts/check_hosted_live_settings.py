"""Check opt-in live settings before installing dependencies; no network calls.

Only fixed labels and booleans leave this process. A settings pass does not
verify credentials, provider access, quota, billing state or answer quality.
"""
from __future__ import annotations

import json
import os
from typing import Mapping


def inspect_settings(env: Mapping[str, str]) -> dict:
    def present(name: str) -> bool:
        return bool(str(env.get(name, "") or "").strip())

    def confirmed(name: str) -> bool:
        return str(env.get(name, "") or "").strip().lower() in {"true", "1", "yes", "on"}

    checks = {
        "zero_cost_only_enabled": confirmed("ZERO_COST_ONLY"),
        "gemini_key_present": present("GEMINI_API_KEY"),
        "gemini_confirmation_flag_accepted": confirmed("GEMINI_ZERO_COST_CONFIRMED"),
        "model_identifier_present": present("GEMINI_MODEL"),
    }
    codes = {
        "zero_cost_only_enabled": "zero_cost_only_required",
        "gemini_key_present": "gemini_key_missing",
        "gemini_confirmation_flag_accepted": "gemini_zero_cost_confirmation_required",
        "model_identifier_present": "explicit_model_identifier_required",
    }
    blockers = [codes[name] for name, passed in checks.items() if not passed]
    return {
        "schema": 1,
        "state": "SETTINGS_PRESENT" if not blockers else "BLOCKED",
        "passed": not blockers,
        "checks": checks,
        "blocker_codes": blockers,
        "provider_access_verified": False,
        "billing_state_verified": False,
        "network_calls": 0,
        "contains_credentials": False,
    }


def main() -> int:
    report = inspect_settings(os.environ)
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
