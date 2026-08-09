"""Tests for the FMP HTTP client, with an emphasis on not leaking the key.

No network: `requests.get` is replaced throughout.
"""

import pytest
import requests

from data import fmp_client
from data.fmp_client import FMPClient, FMPError

KEY = 'secret-key-value'


class FakeResponse:
    def __init__(self, status_code=200, payload=None, body_is_json=True):
        self.status_code = status_code
        self._payload = payload if payload is not None else [{'symbol': 'AAPL'}]
        self._body_is_json = body_is_json

    def json(self):
        if not self._body_is_json:
            raise ValueError('no JSON object could be decoded')
        return self._payload


@pytest.fixture
def calls(monkeypatch):
    """Record every outgoing request instead of making one."""
    recorded = []

    def fake_get(url, params=None, headers=None, timeout=None):
        recorded.append({'url': url, 'params': params or {}, 'headers': headers or {}})
        return FakeResponse()

    monkeypatch.setattr(fmp_client.requests, 'get', fake_get)
    return recorded


# --------------------------------------------------------------------------
# Key handling
# --------------------------------------------------------------------------

def test_key_is_sent_as_a_header_not_a_query_parameter(calls):
    FMPClient(KEY).quote('AAPL')
    assert len(calls) == 1
    assert calls[0]['headers']['apikey'] == KEY
    assert 'apikey' not in calls[0]['params']


def test_query_parameter_auth_is_used_only_after_a_header_rejection(monkeypatch):
    seen = []

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.append({'params': params or {}, 'headers': headers or {}})
        return FakeResponse(status_code=401) if len(seen) == 1 else FakeResponse()

    monkeypatch.setattr(fmp_client.requests, 'get', fake_get)
    FMPClient(KEY).quote('AAPL')

    assert len(seen) == 2
    assert seen[0]['headers']['apikey'] == KEY and 'apikey' not in seen[0]['params']
    assert seen[1]['params']['apikey'] == KEY and not seen[1]['headers']


def test_the_key_never_reaches_the_error_message(monkeypatch):
    # requests puts the full URL in its exception text. When the key travels
    # as a query parameter that text carries the credential straight into
    # logs and terminals, which is exactly what this guards.
    leaky = ('Max retries exceeded with url: '
             '/stable/quote?symbol=AAPL&apikey=%s (Caused by ProxyError)' % KEY)

    def fake_get(*args, **kwargs):
        raise requests.RequestException(leaky)

    monkeypatch.setattr(fmp_client.requests, 'get', fake_get)

    with pytest.raises(FMPError) as excinfo:
        FMPClient(KEY).quote('AAPL')

    assert KEY not in str(excinfo.value)
    assert '***' in str(excinfo.value)


def test_no_chained_exception_can_carry_the_key(monkeypatch):
    def fake_get(*args, **kwargs):
        raise requests.RequestException('boom apikey=%s' % KEY)

    monkeypatch.setattr(fmp_client.requests, 'get', fake_get)

    with pytest.raises(FMPError) as excinfo:
        FMPClient(KEY).quote('AAPL')

    # `raise ... from None`: a chained cause would put the original text,
    # key included, back into the printed traceback.
    assert excinfo.value.__cause__ is None


def test_upstream_error_text_is_redacted(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return FakeResponse(payload={'Error Message': 'Invalid key %s' % KEY})

    monkeypatch.setattr(fmp_client.requests, 'get', fake_get)

    with pytest.raises(FMPError) as excinfo:
        FMPClient(KEY).quote('AAPL')

    assert KEY not in str(excinfo.value)


# --------------------------------------------------------------------------
# Request shape
# --------------------------------------------------------------------------

def test_endpoints_hit_the_documented_stable_paths(calls):
    client = FMPClient(KEY)
    client.profile('AAPL')
    client.quote('AAPL')
    client.key_metrics('AAPL')
    client.ratios('AAPL')
    client.growth('AAPL')
    client.rsi('AAPL')

    assert [c['url'].rsplit('/stable/', 1)[1] for c in calls] == [
        'profile', 'quote', 'key-metrics', 'ratios',
        'financial-growth', 'technical-indicators/rsi']


def test_symbol_is_passed_as_the_symbol_parameter(calls):
    FMPClient(KEY).quote('aapl')
    assert calls[0]['params']['symbol'] == 'aapl'


def test_rsi_requests_a_daily_window(calls):
    FMPClient(KEY).rsi('AAPL', period=14)
    assert calls[0]['params']['periodLength'] == 14
    assert calls[0]['params']['timeframe'] == '1day'


def test_base_url_is_the_stable_api():
    assert FMPClient(KEY).base_url.endswith('/stable')


# --------------------------------------------------------------------------
# Failure handling
# --------------------------------------------------------------------------

def test_non_200_raises_without_echoing_parameters(monkeypatch):
    monkeypatch.setattr(fmp_client.requests, 'get',
                        lambda *a, **k: FakeResponse(status_code=500))
    with pytest.raises(FMPError) as excinfo:
        FMPClient(KEY).quote('AAPL')
    assert '500' in str(excinfo.value)
    assert KEY not in str(excinfo.value)


def test_non_json_body_raises(monkeypatch):
    monkeypatch.setattr(fmp_client.requests, 'get',
                        lambda *a, **k: FakeResponse(body_is_json=False))
    with pytest.raises(FMPError):
        FMPClient(KEY).quote('AAPL')
