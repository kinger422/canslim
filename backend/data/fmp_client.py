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

    def _redact(self, text) -> str:
        """Strip the API key out of anything headed for a log or a screen.

        requests embeds the full request URL in its exception text, so a key
        passed as a query parameter ends up in tracebacks, terminals and
        error trackers. Header auth keeps it out of the URL in the first
        place; this is the second line of defence for the fallback path and
        for any message that quotes upstream text.
        """
        text = str(text)
        return text.replace(self.api_key, '***') if self.api_key else text

    def _send(self, url, params, in_header):
        """One attempt, authenticating by header or by query parameter."""
        headers = {'apikey': self.api_key} if in_header else None
        if not in_header:
            params = dict(params, apikey=self.api_key)
        return requests.get(url, params=params, headers=headers, timeout=self.timeout)

    def _get(self, path: str, **params):
        url = '%s/%s' % (self.base_url, path.lstrip('/'))
        try:
            # Header auth by preference: it keeps the key out of the URL, and
            # so out of every log line and exception message. FMP documents
            # both forms, so fall back to the query parameter if a plan or
            # endpoint only honours that one.
            response = self._send(url, params, in_header=True)
            if response.status_code in (401, 403):
                response = self._send(url, params, in_header=False)
        except requests.RequestException as exc:
            raise FMPError('request to %s failed: %s' % (path, self._redact(exc))) from None

        if response.status_code != 200:
            raise FMPError('%s returned HTTP %d' % (path, response.status_code))

        try:
            payload = response.json()
        except ValueError:
            raise FMPError('%s returned a non-JSON body' % path) from None

        if isinstance(payload, dict) and payload.get('Error Message'):
            raise FMPError('%s: %s' % (path, self._redact(payload['Error Message'])))
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
