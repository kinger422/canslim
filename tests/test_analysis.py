"""Tests for the composed analysis, including the live/stub boundary.

No network: a fake client stands in for FMPClient, which is the whole point
of keeping `build_analysis` free of FastAPI and of the HTTP client.
"""

import pytest

from analysis import build_analysis
from data.fmp_client import FMPClient, FMPError
from tests.test_mapping import SOURCES


class FakeClient:
    """Returns canned rows and records which endpoints were called."""

    def __init__(self, sources=None, fail=False):
        self.sources = SOURCES if sources is None else sources
        self.fail = fail
        self.calls = []

    def _row(self, name, ticker):
        self.calls.append((name, ticker))
        if self.fail:
            raise FMPError('simulated outage')
        return self.sources.get(name, {})

    def quote(self, ticker):
        return self._row('quote', ticker)

    def key_metrics(self, ticker):
        return self._row('key_metrics', ticker)

    def ratios(self, ticker):
        return self._row('ratios', ticker)

    def growth(self, ticker):
        return self._row('growth', ticker)

    def rsi(self, ticker):
        return self._row('rsi', ticker)


# --------------------------------------------------------------------------
# Stub mode — no key configured
# --------------------------------------------------------------------------

def test_stub_mode_is_labelled_as_such():
    result = build_analysis('aapl', client=None)
    assert result['data_source'] == 'stub'
    assert result['complete'] is False
    assert 'FMP_API_KEY' in result['warning']


def test_stub_mode_still_produces_a_full_response():
    result = build_analysis('AAPL', client=None)
    assert result['ticker'] == 'AAPL'
    assert result['committee']['recommendation'] == 'BUY'


# --------------------------------------------------------------------------
# Live mode
# --------------------------------------------------------------------------

def test_live_mode_scores_from_the_api_payload():
    result = build_analysis('aapl', client=FakeClient())
    assert result['data_source'] == 'live'
    assert result['complete'] is True
    assert result['ticker'] == 'AAPL'
    # Derived from SOURCES: strong quality and trend, expensive on value.
    assert result['fundamental']['quality_score'] == 40
    assert result['valuation']['valuation_score'] == 15
    assert result['technical']['technical_score'] == 100
    assert result['committee']['recommendation'] == 'SELL'
    assert result['committee']['confidence'] == 52


def test_live_mode_queries_every_endpoint_once():
    client = FakeClient()
    build_analysis('MSFT', client=client)
    assert [name for name, _ in client.calls] == [
        'quote', 'key_metrics', 'ratios', 'growth', 'rsi']
    assert {ticker for _, ticker in client.calls} == {'MSFT'}


def test_complete_response_carries_no_warning():
    result = build_analysis('AAPL', client=FakeClient())
    assert 'warning' not in result
    assert 'missing_fields' not in result


def test_coverage_is_reported_per_agent():
    result = build_analysis('AAPL', client=FakeClient())
    assert result['coverage'] == {
        'fundamental': '5/5', 'valuation': '3/3', 'technical': '4/4'}


# --------------------------------------------------------------------------
# The failure mode this layer exists to prevent
# --------------------------------------------------------------------------

def test_unmapped_fields_are_flagged_rather_than_scored_as_a_sell():
    # If FMP renames its fields, every metric goes missing, every agent
    # scores its pessimistic default, and the committee returns a confident
    # SELL on a company it knows nothing about. That verdict must never
    # leave the service unmarked.
    result = build_analysis('AAPL', client=FakeClient(sources={}))

    assert result['committee']['recommendation'] == 'SELL'
    assert result['complete'] is False
    assert len(result['missing_fields']) == 12
    assert 'should not be acted on' in result['warning']
    assert result['coverage'] == {
        'fundamental': '0/5', 'valuation': '0/3', 'technical': '0/4'}


def test_partial_data_is_flagged_even_when_most_fields_arrive():
    result = build_analysis('AAPL', client=FakeClient(
        sources=dict(SOURCES, growth={})))
    assert result['complete'] is False
    assert result['missing_fields'] == ['epsGrowth', 'revenueGrowth']
    assert result['coverage']['fundamental'] == '3/5'


def test_upstream_failure_raises_rather_than_falling_back_to_stubs():
    # A data outage must not be answered with placeholder numbers.
    with pytest.raises(FMPError):
        build_analysis('AAPL', client=FakeClient(fail=True))


# --------------------------------------------------------------------------
# Client configuration
# --------------------------------------------------------------------------

def test_from_env_returns_none_when_unconfigured(monkeypatch):
    monkeypatch.delenv('FMP_API_KEY', raising=False)
    assert FMPClient.from_env() is None


def test_from_env_ignores_a_blank_key(monkeypatch):
    monkeypatch.setenv('FMP_API_KEY', '   ')
    assert FMPClient.from_env() is None


def test_from_env_builds_a_client_when_configured(monkeypatch):
    monkeypatch.setenv('FMP_API_KEY', 'test-key')
    client = FMPClient.from_env()
    assert client is not None
    assert client.api_key == 'test-key'


def test_client_rejects_an_empty_key():
    with pytest.raises(ValueError):
        FMPClient('')


def test_first_row_extraction_handles_both_payload_shapes():
    assert FMPClient._first([{'a': 1}, {'a': 2}]) == {'a': 1}
    assert FMPClient._first({'a': 1}) == {'a': 1}
    assert FMPClient._first([]) == {}
    assert FMPClient._first(None) == {}
