"""
Research Depth Modes — Spec Section 13

QUICK / DEEP / MAXIMUM / CUSTOM.

IMPORTANT (Spec Section 13): "Maximum" ka matlab unlimited internet NAHI hai.
Gemini free tier ~20 requests/din hai, isliye har mode ka call budget yahan
explicitly likha hai aur final answer mein honestly report hota hai.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, Optional


@dataclass
class DepthConfig:
    name: str = "DEEP"
    gemini_calls: int = 2          # is mode mein maximum kitni Gemini calls
    max_sources: int = 10          # ranking ke baad kitne sources use honge
    max_per_connector: int = 3     # har connector se kitne results
    max_rounds: int = 1            # Spec Section 2 — progressive research rounds
    use_papers: bool = True
    use_books: bool = False
    use_datasets: bool = True       # Spec §2 + §11 — public datasets / raw data
    # Patents (₹0 patent batch) — SIRF invention/prior-art wale sawaalon par
    # chalta hai, aur wo faisla planner ka `patent_intent()` karta hai. Ye flag
    # uske UPAR ka switch hai: QUICK mein patent search ka koi matlab nahi
    # (QUICK ka wada "turant jawab" hai, aur patent APIs slow + fair-use limited
    # hain).
    #
    # CUSTOM mode mein bhi explicit on/off kiya ja sakta hai. Request schemas aur
    # BOOL_FIELDS ek hi naam expose karte hain, isliye documented switch aur
    # runtime config alag nahi ho sakte.
    use_patents: bool = True
    use_red_team: bool = True
    chars_per_source: int = 1200
    # Spec Section 3/4 — kitne top sources ka LEGALLY-FREE full text download
    # karke padha jayega. 0 = sirf snippet/abstract level (koi download nahi).
    # Ye Gemini quota nahi kharch karta, sirf time aur bandwidth leta hai —
    # isliye MAXIMUM mein zyada rakh sakte hain.
    max_fulltext: int = 3
    # Spec Section 13 — "Maximum ka matlab unlimited internet nahi".
    # Gemini calls par rail pehle se thi, par NETWORK par koi rail nahi thi.
    # Har connector 2 attempts x (10s connect + 25s read) le sakta hai, aur
    # arXiv 3-step ladder par 3s gap bhi rakhta hai — worst case DEEP discovery
    # ~7 minute aur MAXIMUM ~15 minute tak ja sakta tha, jismein user ko lagta
    # ki app hang ho gayi. Ye ek round ki discovery ka wall-clock budget hai:
    # jo connector isme poora na ho, wo honestly "deadline" reason ke saath
    # report hota hai — chup-chaap "0 results" nahi banta.
    discovery_seconds: int = 90

    def to_dict(self) -> Dict:
        return asdict(self)


QUICK = DepthConfig(
    name="QUICK", gemini_calls=1, max_sources=5, max_per_connector=2,
    max_rounds=1, use_papers=False, use_books=False, use_datasets=False,
    use_patents=False,
    use_red_team=False,
    chars_per_source=800, max_fulltext=1, discovery_seconds=45,
)

DEEP = DepthConfig(
    name="DEEP", gemini_calls=2, max_sources=10, max_per_connector=3,
    max_rounds=2, use_papers=True, use_books=False, use_datasets=True,
    use_patents=True,
    use_red_team=True,
    chars_per_source=1200, max_fulltext=3, discovery_seconds=90,
)

MAXIMUM = DepthConfig(
    name="MAXIMUM", gemini_calls=3, max_sources=18, max_per_connector=4,
    max_rounds=3, use_papers=True, use_books=True, use_datasets=True,
    use_patents=True,
    use_red_team=True,
    chars_per_source=1500, max_fulltext=6, discovery_seconds=150,
)

_PRESETS = {"QUICK": QUICK, "DEEP": DEEP, "MAXIMUM": MAXIMUM}

# Safety rails — CUSTOM mode mein user in limits se aage nahi ja sakta
_LIMITS = {
    "gemini_calls": (1, 5),
    "max_sources": (1, 40),
    "max_per_connector": (1, 10),
    "max_rounds": (1, 4),
    "chars_per_source": (300, 4000),
    # 0 allowed hai — user full-text download poori tarah band kar sakta hai
    "max_fulltext": (0, 12),
    # 20s se kam rakhne par slow-but-free sources (archive.org) hamesha kat
    # jayenge; 600s se upar user ka sabr khatam ho jaata hai
    "discovery_seconds": (20, 600),
}


def _clamp(field: str, value: int) -> int:
    lo, hi = _LIMITS[field]
    return max(lo, min(int(value), hi))


# CUSTOM mode mein user kaun-kaun se numbers bhej sakta hai — API isi list se
# apna request model aur /depth-modes ka disclosure banata hai. Hand-typed copy
# rakhne par doc aur asli clamp alag ho jaate the, yaani disclosure jhooth.
BOOL_FIELDS = (
    "use_papers", "use_books", "use_datasets", "use_patents", "use_red_team",
)


def depth_limits() -> Dict[str, tuple]:
    """{field: (min, max)} — jo clamp sach mein lagta hai, wahi."""
    return dict(_LIMITS)


def get_depth_config(mode: str = "DEEP", custom: Optional[Dict] = None) -> DepthConfig:
    """
    Mode name se config lo. CUSTOM ke liye user apne numbers de sakta hai
    (Spec Section 13 — "User khud source count/depth/time tay kar sake").
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
        # red team ke liye kam se kam 2 calls chahiye
        if base.use_red_team and base.gemini_calls < 2:
            base.use_red_team = False
        return base

    preset = _PRESETS.get(mode, DEEP)
    return DepthConfig(**asdict(preset))


def quota_note(config: DepthConfig) -> str:
    """Honest quota statement jo final answer mein jaata hai."""
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
