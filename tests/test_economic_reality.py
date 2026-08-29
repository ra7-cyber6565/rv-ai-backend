import math

import pytest

from research_engine.economic_reality import EconomicScenario, assess_economic_reality
from research_engine.economic_reality_wiring import (
    apply_economic_reality_wiring,
    build_economic_reality_packet,
)


def _basis(**overrides):
    value = {
        "initial_capex": "MEASURED",
        "revenues": "ESTIMATED",
        "operating_costs": "MEASURED",
        "discount_rate": "ASSUMED",
    }
    value.update(overrides)
    return value


def _scenario(
    scenario_id="base",
    probability=1.0,
    currency="USD",
    discount_rate=0.0,
    initial_capex=100.0,
    revenues=(70.0, 70.0),
    operating_costs=(10.0, 10.0),
    **kwargs,
):
    return EconomicScenario(
        scenario_id=scenario_id,
        probability=probability,
        currency=currency,
        discount_rate=discount_rate,
        initial_capex=initial_capex,
        revenues=revenues,
        operating_costs=operating_costs,
        provenance_ref=kwargs.pop("provenance_ref", f"ledger:{scenario_id}"),
        input_basis=kwargs.pop("input_basis", _basis()),
        **kwargs,
    )


def test_cash_flow_npv_irr_and_payback_are_deterministic():
    report = assess_economic_reality([_scenario()])
    audit = report.scenario_audits[0]
    assert audit.net_cash_flows == (60.0, 60.0)
    assert audit.npv == pytest.approx(20.0)
    assert audit.irr_status == "unique_bounded_root"
    assert audit.irr == pytest.approx(0.130662386, rel=1e-6)
    assert audit.payback_period == pytest.approx(1 + 40 / 60)
    assert audit.discounted_payback_period == audit.payback_period
    assert report.expected_npv == pytest.approx(20.0)
    assert report.economic_signal == "POSITIVE_ACROSS_SUPPLIED_SCENARIOS"


def test_discounted_npv_uses_explicit_rate_without_hidden_adjustments():
    report = assess_economic_reality([
        _scenario(discount_rate=0.10, revenues=(65.0, 65.0), operating_costs=(10.0, 10.0))
    ])
    expected = -100 + 55 / 1.1 + 55 / (1.1**2)
    assert report.scenario_audits[0].npv == pytest.approx(expected)
    assert report.taxes_or_inflation_inferred is False
    assert report.currency_conversion_performed is False


def test_unit_economics_compute_contribution_and_break_even():
    scenario = _scenario(
        unit_price=10.0,
        unit_variable_cost=6.0,
        fixed_cost_per_period=100.0,
        input_basis=_basis(unit_economics="CONTRACTED"),
    )
    audit = assess_economic_reality([scenario]).scenario_audits[0]
    assert audit.contribution_margin_per_unit == 4.0
    assert audit.break_even_units_per_period == 25.0
    assert audit.break_even_status == "computed_from_supplied_unit_economics"


def test_non_positive_unit_margin_refuses_fake_break_even():
    scenario = _scenario(
        unit_price=5.0,
        unit_variable_cost=6.0,
        fixed_cost_per_period=100.0,
        input_basis=_basis(unit_economics="ESTIMATED"),
    )
    audit = assess_economic_reality([scenario]).scenario_audits[0]
    assert audit.contribution_margin_per_unit == -1.0
    assert audit.break_even_units_per_period is None
    assert audit.break_even_status == "non_positive_contribution_margin"


def test_multiple_cash_flow_sign_changes_do_not_claim_unique_irr():
    scenario = _scenario(
        initial_capex=100.0,
        revenues=(230.0, 0.0),
        operating_costs=(0.0, 0.0),
        other_cash_flows=(0.0, -132.0),
        input_basis=_basis(other_cash_flows="CONTRACTED"),
    )
    audit = assess_economic_reality([scenario]).scenario_audits[0]
    assert audit.irr is None
    assert audit.irr_status == "undefined_or_non_unique_sign_pattern"


def test_probability_weighted_scenarios_and_mixed_signal():
    good = _scenario("good", probability=0.75, revenues=(80.0, 80.0))
    bad = _scenario("bad", probability=0.25, revenues=(20.0, 20.0))
    report = assess_economic_reality([good, bad])
    good_npv = 40.0
    bad_npv = -80.0
    assert report.expected_npv == pytest.approx(0.75 * good_npv + 0.25 * bad_npv)
    assert report.worst_case_npv == bad_npv
    assert report.best_case_npv == good_npv
    assert report.probability_of_positive_npv == pytest.approx(0.75)
    assert report.economic_signal == "MIXED_SCENARIO_ECONOMICS"


def test_negative_expected_value_is_not_promising():
    report = assess_economic_reality([
        _scenario(revenues=(20.0, 20.0), operating_costs=(10.0, 10.0))
    ])
    assert report.expected_npv < 0
    assert report.economically_promising_under_assumptions is False
    assert report.economic_signal == "NOT_PROMISING_UNDER_STATED_ASSUMPTIONS"


def test_sensitivity_is_deterministic_and_ranks_absolute_impact():
    first = assess_economic_reality([_scenario()])
    second = assess_economic_reality([_scenario()])
    assert first.sensitivities == second.sensitivities
    impacts = [abs(row.delta_from_base) for row in first.sensitivities]
    assert impacts == sorted(impacts, reverse=True)
    by_name = {row.shock: row for row in first.sensitivities}
    assert by_name["revenue_-10pct"].expected_npv < first.expected_npv
    assert by_name["opex_+10pct"].expected_npv < first.expected_npv
    assert by_name["capex_+10pct"].expected_npv < first.expected_npv


def test_liquidity_floor_is_separate_from_positive_npv():
    scenario = _scenario(
        initial_capex=100.0,
        starting_cash=20.0,
        revenues=(0.0, 250.0),
        operating_costs=(0.0, 0.0),
        input_basis=_basis(starting_cash="MEASURED"),
    )
    audit = assess_economic_reality([scenario]).scenario_audits[0]
    assert audit.npv > 0
    assert audit.minimum_cash_balance == -80.0
    assert audit.liquidity_breach is True


def test_hashes_are_reproducible_and_assumption_sensitive():
    first = assess_economic_reality([_scenario()])
    second = assess_economic_reality([_scenario()])
    changed = assess_economic_reality([_scenario(revenues=(71.0, 70.0))])
    assert first.assumptions_sha256 == second.assumptions_sha256
    assert first.report_sha256 == second.report_sha256
    assert changed.assumptions_sha256 != first.assumptions_sha256
    assert changed.report_sha256 != first.report_sha256


def test_nan_inf_and_invalid_probability_fail_closed():
    with pytest.raises(ValueError, match="finite"):
        assess_economic_reality([_scenario(revenues=(math.nan, 70.0))])
    with pytest.raises(ValueError, match="finite"):
        assess_economic_reality([_scenario(discount_rate=math.inf)])
    with pytest.raises(ValueError, match="probability"):
        assess_economic_reality([_scenario(probability=1.1)])


def test_probabilities_must_sum_to_one():
    with pytest.raises(ValueError, match="sum"):
        assess_economic_reality([
            _scenario("a", probability=0.4),
            _scenario("b", probability=0.4),
        ])


def test_currency_conversion_is_never_silently_inferred():
    with pytest.raises(ValueError, match="same currency"):
        assess_economic_reality([
            _scenario("usd", probability=0.5, currency="USD"),
            _scenario("eur", probability=0.5, currency="EUR"),
        ])


def test_scenario_horizons_must_match():
    with pytest.raises(ValueError, match="same period horizon"):
        assess_economic_reality([
            _scenario("a", probability=0.5, revenues=(70.0, 70.0)),
            _scenario(
                "b",
                probability=0.5,
                revenues=(70.0, 70.0, 70.0),
                operating_costs=(10.0, 10.0, 10.0),
            ),
        ])


def test_provenance_and_input_basis_are_mandatory():
    with pytest.raises(ValueError, match="provenance"):
        assess_economic_reality([_scenario(provenance_ref="")])
    with pytest.raises(ValueError, match="input_basis is missing"):
        assess_economic_reality([_scenario(input_basis={"revenues": "MEASURED"})])
    with pytest.raises(ValueError, match="invalid"):
        assess_economic_reality([_scenario(input_basis=_basis(revenues="MAGIC"))])


def test_report_never_claims_profitability_or_real_world_viability():
    report = assess_economic_reality([_scenario(revenues=(1000.0, 1000.0))])
    assert report.expected_npv > 0
    assert report.economically_promising_under_assumptions is True
    assert report.profitability_proven is False
    assert report.real_world_viability_proven is False
    assert report.market_demand_proven is False
    assert report.truth_proven is False


def test_wiring_does_not_infer_economics_from_free_form_text():
    packet = build_economic_reality_packet({
        "question": "Will this product make money? Price might be $99 and demand huge.",
        "answer": "maybe",
        "coverage": {},
    })
    assert packet["status"] == "NO_STRUCTURED_ECONOMIC_INPUTS"
    assert packet["free_form_economics_inference_performed"] is False
    assert packet["profitability_proven"] is False


def test_wiring_audits_explicit_contract_without_upgrading_parent_result():
    result = {
        "status": "PARTIAL",
        "answer": "original answer",
        "coverage": {
            "economic_reality_inputs": {
                "scenarios": [
                    {
                        "scenario_id": "base",
                        "probability": 1.0,
                        "currency": "USD",
                        "discount_rate": 0.0,
                        "initial_capex": 100.0,
                        "revenues": [70.0, 70.0],
                        "operating_costs": [10.0, 10.0],
                        "provenance_ref": "ledger:base",
                        "input_basis": _basis(),
                    }
                ]
            }
        },
    }
    wired = apply_economic_reality_wiring(result)
    packet = wired["coverage"]["economic_reality"]
    assert packet["status"] == "AUDITED"
    assert packet["expected_npv"] == pytest.approx(20.0)
    assert packet["profitability_proven"] is False
    assert wired["status"] == "PARTIAL"
    assert wired["answer"] == "original answer"


def test_wiring_unknown_or_incomplete_schema_fails_closed_without_crashing_result():
    result = apply_economic_reality_wiring({
        "coverage": {
            "economic_reality_inputs": {
                "scenarios": [{"scenario_id": "x", "surprise": 1}]
            }
        }
    })
    packet = result["coverage"]["economic_reality"]
    assert packet["status"] == "ASSESSMENT_ERROR"
    assert packet["ran"] is False
    assert packet["profitability_proven"] is False
    assert packet["real_world_viability_proven"] is False
