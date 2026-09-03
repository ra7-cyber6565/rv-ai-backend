"""Pytest bootstrap for repository-local imports.

GitHub Actions can invoke pytest with the tests directory first on ``sys.path``
instead of the repository root.  Production modules such as ``research_engine``
and ``scripts`` must therefore be made importable centrally for every test,
rather than each test file carrying a private path hack.

This file is test-only: it performs no network/model/provider call and does not
change production runtime behavior.
"""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
root_text = str(ROOT)
if root_text not in sys.path:
    sys.path.insert(0, root_text)
