"""Tests for the Apex Equity Research scoring agents.

These agents are pure functions over dicts — no network, no API key, no
FastAPI — so they are the part of the backend that can be tested honestly
today. Each test pins behaviour that already exists rather than asserting
what the scoring "should" be.
"""

from agents.committee import CommitteeAgent
from agents.fundamental import FundamentalAgent
from agents.technical import TechnicalAgent
from agents.valuation import ValuationAgent


# --------------------------------------------------------------------------
# FundamentalAgent — five criteria, 20 points each
# --------------------------------------------------------------------------

def test_fundamental_all_criteria_met_scores_100():
    result = FundamentalAgent().score({
        'roic': 20,
        'revenueGrowth': 12,
        'epsGrowth': 15,
        'fcfMargin': 18,
        'debtToEquity': 0.6,
    })
    assert result['quality_score'] == 100


def test_fundamental_missing_metrics_score_zero():
    # Defaults are deliberately pessimistic: 0 for the growth metrics and
    # 999 for debt-to-equity, so an empty payload earns nothing.
    assert FundamentalAgent().score({})['quality_score'] == 0


def test_fundamental_thresholds_are_strict():
    # roic > 15, growth > 10, debtToEquity < 1 — every boundary value misses.
    result = FundamentalAgent().score({
        'roic': 15,
        'revenueGrowth': 10,
        'epsGrowth': 10,
        'fcfMargin': 10,
        'debtToEquity': 1,
    })
    assert result['quality_score'] == 0


def test_fundamental_scores_each_criterion_independently():
    assert FundamentalAgent().score({'roic': 20})['quality_score'] == 20


def test_fundamental_echoes_input_metrics():
    metrics = {'roic': 20}
    assert FundamentalAgent().score(metrics)['metrics'] == metrics


# --------------------------------------------------------------------------
# ValuationAgent — tiered scoring, 100 point ceiling
# --------------------------------------------------------------------------

def test_valuation_cheapest_tier_scores_100():
    result = ValuationAgent().score({
        'peRatio': 10,
        'evToEbitda': 5,
        'fcfYield': 0.10,
    })
    assert result['valuation_score'] == 100


def test_valuation_middle_tier_scores_partial_credit():
    # pe in [15, 25) -> 20, ev in [10, 15) -> 20, fcfYield in (0.03, 0.05] -> 15
    result = ValuationAgent().score({
        'peRatio': 18,
        'evToEbitda': 12,
        'fcfYield': 0.045,
    })
    assert result['valuation_score'] == 55


def test_valuation_missing_metrics_score_zero():
    assert ValuationAgent().score({})['valuation_score'] == 0


def test_valuation_tier_boundaries_fall_to_lower_tier():
    result = ValuationAgent().score({
        'peRatio': 15,
        'evToEbitda': 10,
        'fcfYield': 0.05,
    })
    assert result['valuation_score'] == 55


# --------------------------------------------------------------------------
# TechnicalAgent — trend and momentum
# --------------------------------------------------------------------------

def test_technical_full_uptrend_scores_100():
    result = TechnicalAgent().score({
        'price': 100,
        'sma50': 95,
        'sma200': 90,
        'rsi': 58,
    })
    assert result['technical_score'] == 100


def test_technical_empty_payload_still_scores_rsi_band():
    # Documented quirk: rsi defaults to 50, which sits inside the 40-70 band,
    # so an empty payload scores 30 rather than 0.
    assert TechnicalAgent().score({})['technical_score'] == 30


def test_technical_rsi_band_is_inclusive():
    trend = {'price': 100, 'sma50': 95, 'sma200': 90}
    assert TechnicalAgent().score({**trend, 'rsi': 40})['technical_score'] == 100
    assert TechnicalAgent().score({**trend, 'rsi': 70})['technical_score'] == 100
    assert TechnicalAgent().score({**trend, 'rsi': 39})['technical_score'] == 70
    assert TechnicalAgent().score({**trend, 'rsi': 71})['technical_score'] == 70


def test_technical_echoes_price_series():
    result = TechnicalAgent().score({
        'price': 100,
        'sma50': 95,
        'sma200': 90,
        'rsi': 58,
    })
    assert (result['price'], result['sma50'], result['sma200'], result['rsi']) == (100, 95, 90, 58)


# --------------------------------------------------------------------------
# CommitteeAgent — majority vote across the three scores
# --------------------------------------------------------------------------

def test_committee_unanimous_buy():
    result = CommitteeAgent().evaluate(100, 100, 100)
    assert result['recommendation'] == 'BUY'
    assert result['buy_votes'] == 3
    assert result['confidence'] == 100


def test_committee_unanimous_sell():
    result = CommitteeAgent().evaluate(0, 0, 0)
    assert result['recommendation'] == 'SELL'
    assert result['sell_votes'] == 3


def test_committee_majority_of_two_carries():
    assert CommitteeAgent().evaluate(100, 100, 0)['recommendation'] == 'BUY'
    assert CommitteeAgent().evaluate(100, 0, 0)['recommendation'] == 'SELL'


def test_committee_split_vote_holds():
    # One buy, one hold, one sell — no majority, so it falls through to HOLD.
    result = CommitteeAgent().evaluate(70, 60, 10)
    assert result['recommendation'] == 'HOLD'
    assert (result['buy_votes'], result['hold_votes'], result['sell_votes']) == (1, 1, 1)


def test_committee_vote_thresholds():
    assert CommitteeAgent().evaluate(70, 70, 70)['recommendation'] == 'BUY'
    assert CommitteeAgent().evaluate(69, 69, 69)['recommendation'] == 'HOLD'
    assert CommitteeAgent().evaluate(50, 50, 50)['recommendation'] == 'HOLD'
    assert CommitteeAgent().evaluate(49, 49, 49)['recommendation'] == 'SELL'


def test_committee_confidence_is_mean_of_three_scores():
    assert CommitteeAgent().evaluate(100, 100, 0)['confidence'] == 67
    assert CommitteeAgent().evaluate(100, 0, 0)['confidence'] == 33


def test_committee_technical_score_defaults_to_neutral():
    # technical_score defaults to 50, which votes HOLD.
    result = CommitteeAgent().evaluate(100, 100)
    assert result['recommendation'] == 'BUY'
    assert result['hold_votes'] == 1


def test_committee_risk_score_is_passed_through_but_not_yet_voted_on():
    # Risk is carried in the response but takes no part in the vote or the
    # confidence figure. The MVP spec lists a Risk Agent that is not built.
    high_risk = CommitteeAgent().evaluate(100, 100, 100, 99)
    low_risk = CommitteeAgent().evaluate(100, 100, 100, 1)
    assert high_risk['risk_score'] == 99
    assert low_risk['risk_score'] == 1
    assert high_risk['recommendation'] == low_risk['recommendation']
    assert high_risk['confidence'] == low_risk['confidence']


# --------------------------------------------------------------------------
# Integration — the three agents feed the committee on matching keys
# --------------------------------------------------------------------------

def test_agent_outputs_wire_into_the_committee():
    fundamental = FundamentalAgent().score({
        'roic': 20,
        'revenueGrowth': 12,
        'epsGrowth': 15,
        'fcfMargin': 18,
        'debtToEquity': 0.6,
    })
    valuation = ValuationAgent().score({
        'peRatio': 10,
        'evToEbitda': 5,
        'fcfYield': 0.10,
    })
    technical = TechnicalAgent().score({
        'price': 100,
        'sma50': 95,
        'sma200': 90,
        'rsi': 58,
    })

    committee = CommitteeAgent().evaluate(
        fundamental['quality_score'],
        valuation['valuation_score'],
        technical['technical_score'],
        25,
    )

    assert committee['recommendation'] == 'BUY'
    assert committee['confidence'] == 100
