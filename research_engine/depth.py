"""
Research Depth Modes — Spec Section 13

QUICK / DEEP / MAXIMUM / MARATHON / CUSTOM.

IMPORTANT (Spec Section 13): "Maximum" ka matlab unlimited internet NAHI hai.
Gemini free tier ~20 requests/din hai, isliye har mode ka call budget yahan
explicitly likha hai aur final answer mein honestly report hota hai.

Public product contract: QUICK is Chat. MAXIMUM is the single user-facing
unified research orchestrator. Legacy DEEP/MARATHON/COMPANY/COMPANY_PLUS names
remain for API/backward compatibility and focused testing, but MAXIMUM inherits
the strongest bounded research rails rather than making the user choose them.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, Optional


@dataclass
class DepthConfig:
    name: str = "DEEP"
    gemini_calls: int = 2
    max_sources: int = 10
    max_per_connector: int = 3
    max_rounds: int = 1
    use_papers: bool = True
    use_books: bool = False
    use_datasets: bool = True
    use_patents: bool = True
    use_red_team: bool = True
    chars_per_source: int = 1200
    max_fulltext: int = 3
    discovery_seconds: int = 90
    require_all_rounds: bool = False
    research_process_target_percent: int = 0
    company_agents: int = 0

    def to_dict(self) -> Dict:
        return asdict(self)


QUICK = DepthConfig(
    name="QUICK", gemini_calls=1, max_sources=5, max_per_connector=2,
    max_rounds=1, use_papers=False, use_books=False, use_datasets=False,
    use_patents=False, use_red_team=False,
    chars_per_source=800, max_fulltext=1, discovery_seconds=45,
)

DEEP = DepthConfig(
    name="DEEP", gemini_calls=2, max_sources=10, max_per_connector=3,
    max_rounds=2, use_papers=True, use_books=False, use_datasets=True,
    use_patents=True, use_red_team=True,
    chars_per_source=1200, max_fulltext=3, discovery_seconds=90,
)

# Kept as a named compatibility object. get_depth_config("MAXIMUM") below
# intentionally returns the unified strongest bounded config instead.
MAXIMUM = DepthConfig(
    name="MAXIMUM", gemini_calls=3, max_sources=18, max_per_connector=4,
    max_rounds=3, use_papers=True, use_books=True, use_datasets=True,
    use_patents=True, use_red_team=True,
    chars_per_source=1500, max_fulltext=6, discovery_seconds=150,
)

MARATHON = DepthConfig(
    name="MARATHON", gemini_calls=4, max_sources=40, max_per_connector=6,
    max_rounds=5, use_papers=True, use_books=True, use_datasets=True,
    use_patents=True, use_red_team=True, chars_per_source=2200,
    max_fulltext=16, discovery_seconds=360, require_all_rounds=True,
    research_process_target_percent=90,
)

_PRESETS = {
    "QUICK": QUICK,
    "DEEP": DEEP,
    "MAXIMUM": MAXIMUM,
    "MARATHON": MARATHON,
    "COMPANY": DepthConfig(**{**asdict(MARATHON), "name": "COMPANY",
                              "company_agents": 4, "gemini_calls": 8}),
    "COMPANY_PLUS": DepthConfig(**{**asdict(MARATHON), "name": "COMPANY_PLUS",
                                   "company_agents": 6, "gemini_calls": 10}),
}

_LIMITS = {
    "gemini_calls": (1, 5),
    "max_sources": (1, 40),
    "max_per_connector": (1, 10),
    "max_rounds": (1, 4),
    "chars_per_source": (300, 4000),
    "max_fulltext": (0, 12),
    "discovery_seconds": (20, 600),
}


def _clamp(field: str, value: int) -> int:
    lo, hi = _LIMITS[field]
    return max(lo, min(int(value), hi))


BOOL_FIELDS = (
    "use_papers", "use_books", "use_datasets", "use_patents", "use_red_team",
)


def depth_limits() -> Dict[str, tuple]:
    """{field: (min, max)} — jo clamp sach mein lagta hai, wahi."""
    return dict(_LIMITS)


def get_depth_config(mode: str = "DEEP", custom: Optional[Dict] = None) -> DepthConfig:
    """Return an isolated config for one research run.

    MAXIMUM is deliberately the public unified super-orchestrator: it receives
    MARATHON's full-round retrieval/full-text rails plus COMPANY_PLUS's six
    first-pass specialist roles and chief budget. The six roles already contain
    the original four COMPANY roles, so those four are not redundantly executed
    twice. Domain-specific tools remain relevance-gated inside the orchestrator.
    """
    mode = (mode or "DEEP").upper()

    if mode == "CUSTOM":
        base = DepthConfig(**asdict(DEEP))
        base.name = "CUSTOM"
        for key, value in (custom or {}).items():
            if key in _LIMITS and value is not None:
                setattr(base, key, _clamp(key, value))
            elif key in BOOL_FIELDS and value is not None:
                setattr(base, key, bool(value))
        if base.use_red_team and base.gemini_calls < 2:
            base.use_red_team = False
        return base

    if mode == "MAXIMUM":
        # COMPANY_PLUS is MARATHON + six workers. ROLES[:6] contains the
        # original four Company roles (evidence, validation, mechanism,
        # red_team) plus data_quality and implementation. This makes Max a
        # strict capability superset without wasting quota on duplicate workers.
        unified = DepthConfig(**asdict(_PRESETS["COMPANY_PLUS"]))
        unified.name = "MAXIMUM"
        return unified

    preset = _PRESETS.get(mode, DEEP)
    return DepthConfig(**asdict(preset))


def quota_note(config: DepthConfig) -> str:
    """Honest quota statement jo final answer mein jaata hai."""
    if config.company_agents:
        return (
            f"{config.name}: {config.company_agents} specialist workers + chief; "
            f"maximum {config.gemini_calls} logical reasoning calls total. "
            f"Up to {config.max_sources} sources, {config.max_rounds} search rounds, "
            f"{config.max_fulltext} legally accessible full texts. "
            "Workers share the retrieved corpus; roles are not distinct models or "
            "independent scientific replication. Existing confirmed-zero-cost "
            "routing applies; available provider quota may prevent completion. "
            "Retries can require additional HTTP attempts."
        )
    return (
        f"{config.name} mode: maximum {config.gemini_calls} Gemini call(s), "
        f"up to {config.max_sources} ranked sources, up to {config.max_rounds} "
        f"research round(s), aur up to {config.max_fulltext} source(s) ka "
        f"legally-free full text. Har round ki source-discovery ke liye "
        f"{config.discovery_seconds}s ka wall-clock budget hai (isse aage "
        f"connectors honestly 'deadline' bata kar chhoot jaate hain). "
        f"Gemini free tier ~20 calls/day hai — "
        f"is mode se roughly {max(1, 20 // config.gemini_calls)} sawal/din possible hain."
    )
