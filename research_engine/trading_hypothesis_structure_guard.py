"""Conservative trading-domain augmentation for structured hypothesis test plans.

The generic hypothesis parser intentionally refuses to manufacture missing test-plan
fields.  That remains the rule here.  This guard only copies/normalizes details that
are explicitly present in trading/backtest prose so a real walk-forward plan is not
misreported as structurally empty merely because it uses trading vocabulary.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional


_TRADING_CONTEXT = re.compile(
    r"\b(?:backtest(?:ing)?|walk[- ]?forward|paper trad(?:e|ing)|out[- ]of[- ]sample|"
    r"\boos\b|us100|nasdaq(?:[- ]?100)?|xau/?usd|ohlcv|profit factor|sharpe|"
    r"sortino|drawdown|expectancy|slippage|spread|commission)\b",
    re.IGNORECASE,
)
_TEST_KIND = re.compile(
    r"\b(?:backtest(?:ing)?|walk[- ]?forward|paper trad(?:e|ing)|historical simulation)\b",
    re.IGNORECASE,
)
_DATA_HINT = re.compile(
    r"\b(?:us100|nasdaq(?:[- ]?100)?|xau/?usd|ohlcv|historical (?:data|bars?|candles?)|"
    r"market data|price data|tick data|bars?|candles?|\d+\s*(?:m|min(?:ute)?s?|h|hours?|d|days?)\s+(?:bars?|candles?))\b",
    re.IGNORECASE,
)
_METRIC_HINT = re.compile(
    r"\b(?:profit factor|sharpe(?: ratio)?|sortino(?: ratio)?|expectancy|"
    r"max(?:imum)? drawdown|drawdown|win rate|hit rate|p\s*&?\s*l|pnl|"
    r"net return|total return|cagr|turnover|slippage[- ]adjusted|friction[- ]net)\b",
    re.IGNORECASE,
)
_SUCCESS_HINT = re.compile(
    r"\b(?:success(?:ful)? if|pass(?:es)? if|accept(?:ed)? if|expected signal|if true)\b",
    re.IGNORECASE,
)
_FAILURE_HINT = re.compile(
    r"\b(?:fail(?:s|ed)? if|reject(?:ed)? if|falsif\w* if|null result|if false|rule out)\b",
    re.IGNORECASE,
)
_BASELINE_HINT = re.compile(
    r"\b(?:baseline|benchmark|buy[- ]and[- ]hold|no[- ]trade|control)\b",
    re.IGNORECASE,
)
_STAT_HINT = re.compile(
    r"\b(?:profit factor|sharpe(?: ratio)?|sortino(?: ratio)?|expectancy|"
    r"max(?:imum)? drawdown|win rate|hit rate|confidence interval|bootstrap|"
    r"p[- ]?value|bayes factor)\b",
    re.IGNORECASE,
)


def _segments(text: str) -> list[str]:
    """Return bounded verbatim-ish prose fragments; never synthesize content."""
    out: list[str] = []
    for raw in re.split(r"[\n;]+", text or ""):
        line = raw.strip(" -*\t")
        if len(line) < 4:
            continue
        out.append(line)
        if ":" not in line:
            out.extend(
                part.strip()
                for part in re.split(r",|\band\b|\baur\b", line, flags=re.IGNORECASE)
                if len(part.strip()) >= 4
            )
    # Stable de-duplication, preserving original wording/order.
    return list(dict.fromkeys(out))


def _shortest_matching(parts: Iterable[str], pattern: re.Pattern[str]) -> str:
    matches = [p for p in parts if pattern.search(p)]
    return min(matches, key=len)[:600] if matches else ""


def install() -> None:
    """Augment HypothesisEngine._parse_experiment once, without weakening gates."""
    from .hypothesis import HypothesisEngine

    if getattr(HypothesisEngine, "_trading_structure_guard_installed", False):
        return

    original = HypothesisEngine._parse_experiment

    def guarded_parse_experiment(
        cls,
        text: str,
        falsification: str = "",
        prediction: Optional[object] = None,
        prediction_text: str = "",
    ):
        exp = original(
            text,
            falsification=falsification,
            prediction=prediction,
            prediction_text=prediction_text,
        )
        blob = (text or "").strip()
        if not blob or not _TRADING_CONTEXT.search(blob):
            return exp

        # A vague mention such as "trading idea" is not enough.  We augment only
        # when an actual backtest/validation action is explicitly requested.
        if not _TEST_KIND.search(blob):
            return exp

        if exp is None:
            from .hypothesis import ExperimentStructure
            exp = ExperimentStructure()

        parts = _segments(blob)

        if not exp.experiment_type:
            kind = _shortest_matching(parts, _TEST_KIND)
            if kind:
                # Normalized label is grounded by the explicit test-kind phrase.
                exp.experiment_type = "trading backtest / validation"

        if not exp.setup:
            setup = _shortest_matching(parts, _TEST_KIND)
            if setup:
                exp.setup = setup

        data = _shortest_matching(parts, _DATA_HINT)
        if data:
            if not exp.system_or_sample:
                exp.system_or_sample = data
            if not exp.instrument_or_dataset:
                exp.instrument_or_dataset = data

        metric = _shortest_matching(parts, _METRIC_HINT)
        if metric and not exp.measured_quantity:
            exp.measured_quantity = metric

        baseline = _shortest_matching(parts, _BASELINE_HINT)
        if baseline and not exp.control:
            exp.control = baseline

        stat = _shortest_matching(parts, _STAT_HINT)
        if stat and not exp.statistical_metric:
            exp.statistical_metric = stat

        success = _shortest_matching(parts, _SUCCESS_HINT)
        if success and not exp.expected_signal:
            exp.expected_signal = success

        failure = _shortest_matching(parts, _FAILURE_HINT)
        if failure and not exp.null_result:
            exp.null_result = failure

        return exp

    HypothesisEngine._parse_experiment = classmethod(guarded_parse_experiment)
    HypothesisEngine._trading_structure_guard_installed = True
