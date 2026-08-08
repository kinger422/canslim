"""Financial Modeling Prep HTTP client.

Thin wrapper over the /stable endpoints. Holds no scoring logic — mapping
API payloads onto agent inputs lives in `data/mapping.py`.
"""

import os

import requests

BASE_URL = 'https://financialmodelingprep.com/stable'
TIMEOUT = 30


class FMPError(RuntimeError):
    """Raised when market data could not be retrieved.

    Deliberately distinct from a missing field: a request that fails is an
    outage, and callers must not paper over it with placeholder numbers.
    """


class FMPClient:
    def __init__(self, api_key: str, base_url: str = BASE_URL, timeout: int = TIMEOUT):
        if not api_key:
            raise ValueError('api_key is required')
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout

    @classmethod
    def from_env(cls, env_var: str = 'FMP_API_KEY'):
        """Build a client from the environment, or return None if unconfigured.

        Returning None rather than raising lets the caller choose between
        running on stub data and refusing to answer.
        """
        key = os.environ.get(env_var, '').strip()
        return cls(key) if key else None

    def _get(self, path: str, **params):
        params['apikey'] = self.api_key
        url = '%s/%s' % (self.base_url, path.lstrip('/'))
        try:
            response = requests.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise FMPError('request to %s failed: %s' % (path, exc)) from exc

        if response.status_code != 200:
            # The key never appears in the message; params are not echoed.
            raise FMPError('%s returned HTTP %d' % (path, response.status_code))

        try:
            payload = response.json()
        except ValueError as exc:
            raise FMPError('%s returned a non-JSON body' % path) from exc

        if isinstance(payload, dict) and payload.get('Error Message'):
            raise FMPError('%s: %s' % (path, payload['Error Message']))
        return payload

    @staticmethod
    def _first(payload):
        """FMP returns a list for most endpoints; take the newest row."""
        if isinstance(payload, list):
            return payload[0] if payload else {}
        return payload if isinstance(payload, dict) else {}

    def profile(self, ticker: str) -> dict:
        return self._first(self._get('profile', symbol=ticker))

    def quote(self, ticker: str) -> dict:
        return self._first(self._get('quote', symbol=ticker))

    def key_metrics(self, ticker: str) -> dict:
        return self._first(self._get('key-metrics', symbol=ticker, limit=1))

    def ratios(self, ticker: str) -> dict:
        return self._first(self._get('ratios', symbol=ticker, limit=1))

    def growth(self, ticker: str) -> dict:
        return self._first(self._get('financial-growth', symbol=ticker, limit=1))

    def rsi(self, ticker: str, period: int = 14) -> dict:
        return self._first(self._get(
            'technical-indicators/rsi',
            symbol=ticker, periodLength=period, timeframe='1day',
        ))
