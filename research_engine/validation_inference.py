"""Explicit-input statistical inference controls for AI-2.

No alpha, power target, prior, likelihood, correction method, or effect threshold
is defaulted. The module computes only what the caller explicitly supplies.
"""
from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any, Dict, List, Mapping

from .validation_contracts import NOT_TESTED


def _prob(value: Any) -> float | None:
    if isinstance(value, bool): return None
    try: x = float(value)
    except (TypeError, ValueError): return None
    return x if math.isfinite(x) and 0.0 <= x <= 1.0 else None


def bayesian_update(config: Any, *, observed_provenance: bool) -> Any:
    if not isinstance(config, Mapping): return NOT_TESTED
    if not observed_provenance:
        return {"status": NOT_TESTED, "reason": "Bayesian result update requires an observed provenance-bearing receipt."}
    prior = _prob(config.get("prior_h1")); lh1 = _prob(config.get("likelihood_e_given_h1")); lh0 = _prob(config.get("likelihood_e_given_h0"))
    if prior is None or lh1 is None or lh0 is None:
        return {"status": NOT_TESTED, "reason": "prior_h1 and both evidence likelihoods must be explicitly supplied in [0,1]."}
    denominator = prior * lh1 + (1.0 - prior) * lh0
    if denominator <= 0:
        return {"status": NOT_TESTED, "reason": "Supplied likelihood model gives zero probability to the observed evidence."}
    posterior = prior * lh1 / denominator
    bf: Any = lh1 / lh0 if lh0 > 0 else NOT_TESTED
    return {"status": "CALCULATED", "prior_h1": prior, "likelihood_e_given_h1": lh1,
            "likelihood_e_given_h0": lh0, "posterior_h1": posterior,
            "bayes_factor_h1_h0": bf,
            "interpretation_rule": "Posterior/Bayes factor are conditional on supplied prior and likelihood model; no truth threshold is inferred."}


def multiple_testing(config: Any, *, observed_provenance: bool) -> Any:
    if not isinstance(config, Mapping): return NOT_TESTED
    if not observed_provenance:
        return {"status": NOT_TESTED, "reason": "Multiple-testing correction requires provenance-bearing observed test statistics."}
    raw = config.get("p_values")
    if not isinstance(raw, list) or not raw:
        return {"status": NOT_TESTED, "reason": "Explicit p_values list is required."}
    p_values: List[float] = []
    for value in raw:
        p = _prob(value)
        if p is None: return {"status": NOT_TESTED, "reason": "Every p-value must be finite in [0,1]."}
        p_values.append(p)
    method = str(config.get("method") or "").strip().lower(); m = len(p_values)
    if method == "bonferroni":
        adjusted = [min(1.0, p * m) for p in p_values]
    elif method == "holm":
        ordered = sorted(enumerate(p_values), key=lambda pair: pair[1]); adjusted = [0.0] * m; running = 0.0
        for rank, (index, p) in enumerate(ordered):
            running = max(running, min(1.0, (m - rank) * p)); adjusted[index] = running
    else:
        return {"status": NOT_TESTED, "reason": "method must be explicitly supplied as bonferroni or holm."}
    alpha = _prob(config.get("alpha")) if "alpha" in config else None
    out: Dict[str, Any] = {"status": "CALCULATED", "method": method, "raw_p_values": p_values, "adjusted_p_values": adjusted}
    if alpha is not None and 0 < alpha < 1:
        out["alpha"] = alpha; out["reject_flags"] = [p <= alpha for p in adjusted]
    else:
        out["reject_flags"] = NOT_TESTED; out["alpha_rule"] = "No alpha supplied; adjusted p-values are reported without reject/not-reject labels."
    return out


def power_analysis(config: Any) -> Any:
    if not isinstance(config, Mapping): return NOT_TESTED
    try: effect = abs(float(config.get("standardized_effect")))
    except (TypeError, ValueError):
        return {"status": NOT_TESTED, "reason": "Explicit positive standardized_effect is required."}
    alpha = _prob(config.get("alpha")); target_power = _prob(config.get("target_power"))
    sided = config.get("sided")
    if not math.isfinite(effect) or effect <= 0 or alpha is None or not (0 < alpha < 1) or sided not in {1, 2}:
        return {"status": NOT_TESTED, "reason": "standardized_effect>0, alpha in (0,1), and sided=1 or 2 are required."}
    z_alpha = NormalDist().inv_cdf(1.0 - alpha / (2.0 if sided == 2 else 1.0))
    out: Dict[str, Any] = {"status": "CALCULATED", "method": "normal_approximation_equal_groups",
                           "standardized_effect": effect, "alpha": alpha, "sided": sided}
    if target_power is not None and 0 < target_power < 1:
        z_power = NormalDist().inv_cdf(target_power)
        out["target_power"] = target_power
        out["required_n_per_group"] = int(math.ceil(2.0 * ((z_alpha + z_power) / effect) ** 2))
    else:
        out["required_n_per_group"] = NOT_TESTED
        out["target_power_rule"] = "No target_power supplied; required sample size is not invented."
    n = config.get("n_per_group")
    if isinstance(n, int) and not isinstance(n, bool) and n > 0:
        z_effect = effect * math.sqrt(n / 2.0)
        if sided == 1:
            achieved = 1.0 - NormalDist().cdf(z_alpha - z_effect)
        else:
            achieved = 1.0 - NormalDist().cdf(z_alpha - z_effect) + NormalDist().cdf(-z_alpha - z_effect)
        out["n_per_group"] = n; out["approx_achieved_power"] = max(0.0, min(1.0, achieved))
    else:
        out["approx_achieved_power"] = NOT_TESTED
    out["limitation"] = "Approximation only; design-specific variance, clustering, attrition, sequential looks, and non-normal endpoints require a domain model."
    return out


def inference_controls(receipt: Mapping[str, Any], *, observed_provenance: bool) -> Dict[str, Any]:
    return {
        "bayesian_evidence": bayesian_update(receipt.get("bayesian_evidence"), observed_provenance=observed_provenance),
        "multiple_testing_correction": multiple_testing(receipt.get("multiple_testing"), observed_provenance=observed_provenance),
        "power_analysis": power_analysis(receipt.get("power_analysis")),
    }
