"""Small production-safety helpers that need no paid service."""
from __future__ import annotations

import os
from typing import Mapping


def allowed_cors_origins(env: Mapping[str, str] | None = None) -> list[str]:
    """Return explicitly allowed browser origins.

    The web UI is served from the same FastAPI origin, and Android apps do not
    use browser CORS, so the safest default is no cross-origin browser access.
    Set CORS_ALLOWED_ORIGINS to a comma-separated list only when a separate web
    frontend is intentionally deployed.

    Wildcard origins are rejected rather than silently opening the API to every
    website.
    """
    source = env if env is not None else os.environ
    raw = str(source.get("CORS_ALLOWED_ORIGINS", ""))
    origins: list[str] = []
    for item in raw.split(","):
        origin = item.strip().rstrip("/")
        if not origin:
            continue
        if origin == "*":
            raise RuntimeError(
                "CORS_ALLOWED_ORIGINS='*' is not allowed. Add explicit origins instead."
            )
        if not (origin.startswith("https://") or origin.startswith("http://")):
            raise RuntimeError(
                f"Invalid CORS origin '{origin}': expected http:// or https://"
            )
        if origin not in origins:
            origins.append(origin)
    return origins
