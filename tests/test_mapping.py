"""Tests for the FMP payload -> agent input mapping."""

from data.mapping import (FIELD_SPECS, FUNDAMENTAL_KEYS, TECHNICAL_KEYS,
                          VALUATION_KEYS, extract, split)

# Shaped like the /stable rows the client hands over, one row per endpoint.
SOURCES = {
    'quote': {'symbol': 'AAPL', 'price': 240.0, 'priceAvg50': 228.0, 'priceAvg200': 215.0},
    'key_metrics': {'returnOnInvestedCapital': 0.42, 'evToEBITDA': 24.5,
                    'freeCashFlowYield': 0.032},
    'ratios': {'debtToEquityRatio': 1.45, 'priceToEarningsRatio': 32.1,
               'freeCashFlowMargin': 0.26},
    'growth': {'growthRevenue': 0.061, 'growthEPS': 0.098},
    'rsi': {'rsi': 56.4},
}


def test_complete_payload_resolves_every_metric():
    result = extract(SOURCES)
    assert result.missing == []
    assert len(result.metrics) == len(FIELD_SPECS)


def test_ratio_metrics_are_scaled_to_percentages():
    # The agents compare roic > 15 and revenueGrowth > 10 as percentages,
    # while FMP reports ratios. Getting this wrong zeroes every score.
    result = extract(SOURCES)
    assert result.metrics['roic'] == 42.0
    assert round(result.metrics['revenueGrowth'], 4) == 6.1
    assert round(result.metrics['epsGrowth'], 4) == 9.8
    assert result.metrics['fcfMargin'] == 26.0


def test_ratio_metrics_are_left_unscaled():
    result = extract(SOURCES)
    assert result.metrics['debtToEquity'] == 1.45
    assert result.metrics['fcfYield'] == 0.032
    assert result.metrics['peRatio'] == 32.1


def test_resolved_records_which_candidate_matched():
    result = extract(SOURCES)
    assert result.resolved['roic'] == 'returnOnInvestedCapital'
    assert result.resolved['peRatio'] == 'priceToEarningsRatio'


def test_alternate_candidate_names_are_accepted():
    sources = dict(SOURCES, ratios={'debtToEquity': 0.8, 'peRatio': 12.0,
                                    'freeCashFlowMargin': 0.3})
    result = extract(sources)
    assert result.metrics['debtToEquity'] == 0.8
    assert result.resolved['peRatio'] == 'peRatio'


def test_absent_fields_are_reported_not_defaulted():
    result = extract({})
    assert sorted(result.missing) == sorted(s.key for s in FIELD_SPECS)
    # Critically, nothing is invented — a metric that was not reported is
    # simply not present, so callers can tell it apart from a real zero.
    assert result.metrics == {}


def test_partially_missing_payload_reports_only_the_gaps():
    result = extract({'quote': SOURCES['quote']})
    assert 'price' in result.metrics
    assert 'roic' in result.missing
    assert 'price' not in result.missing


def test_non_numeric_values_are_treated_as_missing():
    result = extract({'quote': {'price': 'N/A', 'priceAvg50': None, 'priceAvg200': 215.0}})
    assert 'price' in result.missing
    assert 'sma50' in result.missing
    assert result.metrics['sma200'] == 215.0


def test_non_dict_source_does_not_raise():
    result = extract({'quote': [], 'key_metrics': None})
    assert 'price' in result.missing
    assert 'roic' in result.missing


def test_split_routes_each_metric_to_its_agent():
    fundamental, valuation, technical = split(extract(SOURCES).metrics)
    assert set(fundamental) == set(FUNDAMENTAL_KEYS)
    assert set(valuation) == set(VALUATION_KEYS)
    assert set(technical) == set(TECHNICAL_KEYS)


def test_split_omits_metrics_that_were_never_found():
    fundamental, _, technical = split(extract({'quote': SOURCES['quote']}).metrics)
    assert fundamental == {}
    assert set(technical) == {'price', 'sma50', 'sma200'}
