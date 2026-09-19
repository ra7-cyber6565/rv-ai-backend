#!/usr/bin/env python3
"""Deterministic semantic reconciliation for historical PR81 on current stack.

Run only after the six measured merge conflicts have been resolved by the
integration workflow. This script preserves current compatibility guards while
adding PR81 Round-2/trading acceptance. It performs no network calls.
"""
from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"{label} anchor missing")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_cross_review_capture() -> None:
    path = Path("research_engine/company_cross_review_wiring.py")
    text = path.read_text(encoding="utf-8")
    start_marker = "# Capture the already-installed canonical/compatibility functions once. This\n"
    end_marker = "\n\n\ndef _review_agents(config) -> int:\n"
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    replacement = '''# Capture the fully-installed current compatibility chain. Only unwrap a
# wrapper installed by this module itself (module-reload case). Never trust a
# copied marker on another wrapper: functools.wraps copies function __dict__,
# which can otherwise bypass the current lossless structured-handoff guard.
def _capture_base(fn):
    if (getattr(fn, "__module__", "") == __name__
            and getattr(fn, "__company_cross_review_wiring__", False)):
        return getattr(fn, "__company_cross_review_original__", fn)
    return fn


_ORIGINAL_RUN_COMPANY = _capture_base(_company.run_company)
_ORIGINAL_CHIEF_HANDOFF = _capture_base(_company.chief_handoff)
_ORIGINAL_ATTACH_COMPANY_PASSES = _capture_base(_company.attach_company_passes)
_ORIGINAL_GET_DEPTH_CONFIG = _capture_base(_depth.get_depth_config)
_ORIGINAL_QUOTA_NOTE = _capture_base(_depth.quota_note)
_ORIGINAL_TO_DICT = _capture_base(_depth.DepthConfig.to_dict)'''
    path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")


def patch_craft_wiring() -> None:
    path = Path("research_engine/craft_intent_guard.py")
    text = path.read_text(encoding="utf-8")
    if "company_cross_review_wiring" in text:
        return
    marker = (
        "from .trading_acceptance_guard import install as _install_trading_acceptance_guard\n"
        "_install_trading_acceptance_guard()\n"
    )
    addition = marker + (
        "\n# Unified Max Round-2 collaboration reuses the same Company workers and chief.\n"
        "from .company_cross_review_wiring import install as _install_company_cross_review_wiring\n"
        "_install_company_cross_review_wiring()\n"
    )
    if marker not in text:
        raise SystemExit("craft acceptance wiring anchor missing")
    path.write_text(text.replace(marker, addition, 1), encoding="utf-8")


def patch_unified_max_test() -> None:
    path = Path("tests/test_unified_max_mode.py")
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "def test_maximum_activates_full_company_plus_when_model_layer_is_usable(monkeypatch):",
        "def test_maximum_activates_full_company_plus_and_round2_when_model_layer_is_usable(monkeypatch):",
        1,
    )
    old = "    assert maximum.gemini_calls == company_plus.gemini_calls == 10\n"
    if old in text:
        text = text.replace(
            old,
            "    assert maximum.company_cross_review_agents == 6\n"
            "    assert company_plus.gemini_calls == 10\n"
            "    assert maximum.gemini_calls == 16\n"
            "    assert maximum.to_dict()[\"company_cross_review_agents\"] == 6\n",
            1,
        )
    old2 = "    assert maximum.company_agents == 0\n"
    if old2 in text and "company_cross_review_agents == 0" not in text:
        text = text.replace(old2, old2 + "    assert maximum.company_cross_review_agents == 0\n", 1)
    path.write_text(text, encoding="utf-8")


def patch_runtime_probe() -> None:
    path = Path("tests/test_company_handoff_runtime_wiring.py")
    text = path.read_text(encoding="utf-8")
    old = 'fn = research_company.chief_handoff\nprint(getattr(fn, "__module__", ""))\n'
    new = (
        'fn = research_company.chief_handoff\n'
        'original = getattr(fn, "__company_cross_review_original__", None)\n'
        'print(getattr(fn, "__module__", ""))\n'
        'print(getattr(original, "__bounded_structured_handoff_guard__", False))\n'
    )
    if old not in text:
        raise SystemExit("runtime handoff probe anchor missing")
    text = text.replace(old, new, 1)
    old_assert = (
        '    assert proc.stdout.strip().splitlines()[-1] == '
        '"research_engine.company_handoff_guard"\n'
    )
    new_assert = (
        '    lines = proc.stdout.strip().splitlines()\n'
        '    assert lines[-2] == "research_engine.company_cross_review_wiring"\n'
        '    assert lines[-1] == "True"\n'
    )
    if old_assert not in text:
        raise SystemExit("runtime handoff assertion anchor missing")
    path.write_text(text.replace(old_assert, new_assert, 1), encoding="utf-8")


def patch_trading_runner() -> None:
    path = Path("scripts/run_pr81_trading_live_acceptance.py")
    text = path.read_text(encoding="utf-8")
    if "def run_trading_live()" in text:
        return
    anchor = "\n\ndef _write(path: Path, payload: Mapping[str, Any]) -> None:\n"
    facade = (
        "\n\ndef run_trading_live() -> Dict[str, Any]:\n"
        '    """Hosted-gate compatibility facade over the stronger PR81 Max evaluator."""\n'
        "    receipt = dict(evaluate_result(run_live()))\n"
        '    receipt["schema"] = 3\n'
        "    return receipt\n"
    )
    if anchor not in text:
        raise SystemExit("trading compatibility insertion anchor missing")
    path.write_text(text.replace(anchor, facade + anchor, 1), encoding="utf-8")


def patch_hosted_gate() -> None:
    path = Path("scripts/run_hosted_live_gate.py")
    text = path.read_text(encoding="utf-8")
    start = text.index("REQUIRED_TRADING_CHECKS = {")
    end = text.index("\n\n\ndef summarize_trading", start)
    stronger = '''REQUIRED_TRADING_CHECKS = {
    "status_complete", "maximum_mode_executed", "coding_not_creative",
    "six_workers_requested", "task_contract_complete", "threshold_provenance",
    "trade_contract_ran", "critical_trade_contract", "no_chased_win_rate",
    "trading_reality_boundaries", "three_structured_hypotheses",
    "six_specialists_executed", "specialist_handoff_complete",
    "company_accounting_complete", "chief_executed",
    "implementation_build_executed", "no_false_replication",
}'''
    text = text[:start] + stronger + text[end:]
    text = text.replace('record.get("schema") == 2', 'record.get("schema") == 3', 1)
    old_return = 'return {"schema": 2, "passed": record.get("passed") is True and all(row["passed"] for row in rows),'
    new_return = 'return {"schema": 3, "passed": record.get("passed") is True and all(row["passed"] for row in rows),'
    if old_return not in text:
        raise SystemExit("hosted trading receipt return anchor missing")
    path.write_text(text.replace(old_return, new_return, 1), encoding="utf-8")


def patch_hosted_tests() -> None:
    path = Path("tests/test_hosted_live_gate.py")
    text = path.read_text(encoding="utf-8")
    text = text.replace("{'schema':2,'passed':True,'checks':[", "{'schema':3,'passed':True,'checks':[")
    text = text.replace("{'schema':2,'passed':False,'checks':[", "{'schema':3,'passed':False,'checks':[")
    text = text.replace('{"schema": 2, "passed": True, "checks": [', '{"schema": 3, "passed": True, "checks": [')
    path.write_text(text, encoding="utf-8")


def main() -> int:
    patch_cross_review_capture()
    patch_craft_wiring()
    patch_unified_max_test()
    patch_runtime_probe()
    patch_trading_runner()
    patch_hosted_gate()
    patch_hosted_tests()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
