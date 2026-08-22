"""Run the P0-A patcher with a method-scoped signature guard.

The original assertion guard intentionally aborted before writing because the
short `_check_claims` signature suffix appears in multiple methods. This wrapper
keeps every other exact-match assertion unchanged and narrows only that one
replacement to `FinalQualityGate._check_claims`.
"""
from __future__ import annotations

import apply_p0a_grounding_patch as patcher


_ORIGINAL_LITERAL_ONCE = patcher._literal_once
_TARGET_LABEL = "FinalQualityGate._check_claims signature"
_METHOD_MARKER = "    @staticmethod\n    def _check_claims(\n"
_NEXT_METHOD_MARKER = "\n    @staticmethod\n"


def _method_scoped_literal_once(text: str, old: str, new: str, label: str) -> str:
    if label != _TARGET_LABEL:
        return _ORIGINAL_LITERAL_ONCE(text, old, new, label)

    method_count = text.count(_METHOD_MARKER)
    if method_count != 1:
        raise RuntimeError(
            f"{label}: expected exactly 1 _check_claims method, found {method_count}"
        )

    start = text.index(_METHOD_MARKER)
    end = text.find(_NEXT_METHOD_MARKER, start + len(_METHOD_MARKER))
    if end < 0:
        end = len(text)
    block = text[start:end]
    count = block.count(old)
    if count != 1:
        raise RuntimeError(
            f"{label}: expected exactly 1 signature match inside _check_claims, found {count}"
        )
    patched_block = block.replace(old, new, 1)
    return text[:start] + patched_block + text[end:]


def main() -> int:
    patcher._literal_once = _method_scoped_literal_once
    return patcher.main()


if __name__ == "__main__":
    raise SystemExit(main())
