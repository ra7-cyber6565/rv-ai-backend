"""Hard resource budgets for AI-2 quantitative validation.

These are *compute-safety* limits, not scientific significance thresholds.  They
exist so an untrusted request cannot turn permutation/bootstrap/Monte-Carlo or a
large validation matrix into an unbounded CPU/memory job on the ₹0 backend.

Requests above a hard limit must fail closed with RESOURCE_LIMIT_EXCEEDED.  They
are never silently clamped, because silently doing fewer iterations than the
caller requested would create a misleading validation receipt.
"""
from __future__ import annotations

import math
from typing import Any, Optional, Tuple

# Raw data / structural limits.
MAX_OBSERVATIONS = 50_000
MAX_TWO_GROUP_TOTAL_OBSERVATIONS = 50_000
MAX_CLASS_LABELS = 100
MAX_CLASSIFICATION_WORK_UNITS = 2_000_000  # observations * labels
MAX_P_VALUES = 50_000
MAX_TRADES = 50_000
MAX_TRADING_REGIMES = 128
MAX_HYPOTHESES = 32
MAX_EXECUTION_PACKETS = 32
MAX_VARIABLES = 128
MAX_CONFOUNDERS = 128
MAX_ROBUSTNESS_ROWS = 20_000
MAX_PARAMETER_GRID_ROWS = 20_000
MAX_ABLATION_ROWS = 512
MAX_FAILURE_VALUES = 50_000
MAX_FRICTION_SCENARIOS = 64

# Resampling / stochastic compute limits.
MAX_BOOTSTRAP_RESAMPLES = 50_000
MAX_PERMUTATIONS = 50_000
MAX_BAYES_DRAWS = 100_000
MAX_MONTE_CARLO_SIMULATIONS = 50_000

# Pair iteration count with sample/path size.  This blocks e.g. 50k bootstrap
# resamples over a 50k-row dataset even though each independent count is legal.
MAX_RESAMPLE_WORK_UNITS = 5_000_000
MAX_MONTE_CARLO_WORK_UNITS = 5_000_000
# Trading friction stress constructs one stressed outcome per trade per scenario.
# Keep this separate from Monte Carlo so the receipt names the real workload.
MAX_TRADING_STRESS_WORK_UNITS = 2_000_000

RESOURCE_LIMIT_STATUS = "RESOURCE_LIMIT_EXCEEDED"


def strict_int(value: Any) -> Optional[int]:
    """Parse an exact finite integer without accepting bool/fractional values."""
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(numeric) or not numeric.is_integer():
        return None
    return int(numeric)


def bounded_iterations(
    value: Any,
    *,
    default: int,
    minimum: int,
    maximum: int,
    field: str,
    sample_size: int = 1,
    max_work_units: int | None = None,
) -> Tuple[Optional[int], Optional[dict]]:
    """Validate an iteration request without silently changing it."""
    requested = default if value is None else strict_int(value)
    if requested is None:
        return None, resource_error(field, value, f"must be an integer in [{minimum}, {maximum}]")
    if requested < minimum or requested > maximum:
        return None, resource_error(field, requested, f"must be in [{minimum}, {maximum}]")
    if sample_size < 0:
        return None, resource_error("sample_size", sample_size, "cannot be negative")
    if max_work_units is not None and requested * max(1, sample_size) > max_work_units:
        return None, resource_error(
            field,
            requested,
            f"requested work={requested * max(1, sample_size)} exceeds hard budget {max_work_units}",
        )
    return requested, None


def resource_error(field: str, requested: Any, detail: str) -> dict:
    """Machine-readable fail-closed resource refusal."""
    return {
        "status": RESOURCE_LIMIT_STATUS,
        "reason": f"Validation compute request refused: {field} {detail}.",
        "field": str(field),
        "requested": requested,
        "scientific_result_observed": False,
        "silently_clamped": False,
    }


def bounded_length(values: Any, maximum: int, field: str) -> Optional[dict]:
    """Return a resource error when a sized collection exceeds its hard cap."""
    try:
        size = len(values)
    except (TypeError, AttributeError):
        return None
    if size > maximum:
        return resource_error(field, size, f"count exceeds hard maximum {maximum}")
    return None


__all__ = [
    "MAX_OBSERVATIONS", "MAX_TWO_GROUP_TOTAL_OBSERVATIONS", "MAX_CLASS_LABELS",
    "MAX_CLASSIFICATION_WORK_UNITS", "MAX_P_VALUES", "MAX_TRADES",
    "MAX_TRADING_REGIMES", "MAX_HYPOTHESES", "MAX_EXECUTION_PACKETS", "MAX_VARIABLES",
    "MAX_CONFOUNDERS", "MAX_ROBUSTNESS_ROWS", "MAX_PARAMETER_GRID_ROWS",
    "MAX_ABLATION_ROWS", "MAX_FAILURE_VALUES", "MAX_FRICTION_SCENARIOS",
    "MAX_BOOTSTRAP_RESAMPLES", "MAX_PERMUTATIONS", "MAX_BAYES_DRAWS",
    "MAX_MONTE_CARLO_SIMULATIONS", "MAX_RESAMPLE_WORK_UNITS",
    "MAX_MONTE_CARLO_WORK_UNITS", "MAX_TRADING_STRESS_WORK_UNITS",
    "RESOURCE_LIMIT_STATUS", "strict_int", "bounded_iterations", "resource_error",
    "bounded_length",
]
