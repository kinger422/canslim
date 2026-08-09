"""Compose the scoring agents into a single analysis.

Kept free of FastAPI so the whole decision path is testable without a web
server or a network call. `app.py` is a thin HTTP wrapper over this.
"""

from agents.committee import CommitteeAgent
from agents.fundamental import FundamentalAgent
from agents.technical import TechnicalAgent
from agents.valuation import ValuationAgent
from data.mapping import (FUNDAMENTAL_KEYS, TECHNICAL_KEYS, VALUATION_KEYS,
                          extract, split)

# The placeholder figures the endpoint has returned since it was first
# written. Retained so the service still runs without a key, but labelled
# in the response so they can never be mistaken for market data.
STUB_FUNDAMENTAL = {'roic': 20, 'revenueGrowth': 12, 'epsGrowth': 15,
                    'fcfMargin': 18, 'debtToEquity': 0.6}
STUB_VALUATION = {'peRatio': 18, 'evToEbitda': 12, 'fcfYield': 0.045}
STUB_TECHNICAL = {'price': 100, 'sma50': 95, 'sma200': 90, 'rsi': 58}

DEFAULT_RISK_SCORE = 25

MISSING_FIELD_WARNING = (
    'Some metrics were not present in the API response. The agents treat an '
    'absent metric as a failed criterion, so the scores below understate the '
    'company and the recommendation should not be acted on until the missing '
    'fields are mapped. Run scripts/verify_fmp_fields.py to see which remote '
    'field names your account actually returns.'
)


def _fetch(client, ticker):
    """Collect every endpoint the mapping draws from.

    Five calls per analysis. On the free tier's 250 requests/day that is
    roughly 50 tickers before the quota is spent.
    """
    return {
        'quote': client.quote(ticker),
        'key_metrics': client.key_metrics(ticker),
        'ratios': client.ratios(ticker),
        'growth': client.growth(ticker),
        'rsi': client.rsi(ticker),
    }


def _coverage(missing):
    """Per-agent count of how many inputs arrived."""
    absent = set(missing)
    return {
        'fundamental': '%d/%d' % (len([k for k in FUNDAMENTAL_KEYS if k not in absent]),
                                  len(FUNDAMENTAL_KEYS)),
        'valuation': '%d/%d' % (len([k for k in VALUATION_KEYS if k not in absent]),
                                len(VALUATION_KEYS)),
        'technical': '%d/%d' % (len([k for k in TECHNICAL_KEYS if k not in absent]),
                                len(TECHNICAL_KEYS)),
    }


def _score(fundamental_in, valuation_in, technical_in, risk_score=DEFAULT_RISK_SCORE):
    fundamental = FundamentalAgent().score(fundamental_in)
    valuation = ValuationAgent().score(valuation_in)
    technical = TechnicalAgent().score(technical_in)
    committee = CommitteeAgent().evaluate(
        fundamental['quality_score'],
        valuation['valuation_score'],
        technical['technical_score'],
        risk_score,
    )
    return fundamental, valuation, technical, committee


def build_analysis(ticker: str, client=None) -> dict:
    """Analyse `ticker`, using live data when a client is supplied.

    Raises `data.fmp_client.FMPError` if the upstream call fails — a data
    outage must surface as an error, never as a fallback to placeholders
    dressed up as a recommendation.
    """
    ticker = ticker.upper()

    if client is None:
        fundamental, valuation, technical, committee = _score(
            STUB_FUNDAMENTAL, STUB_VALUATION, STUB_TECHNICAL)
        return {
            'ticker': ticker,
            'data_source': 'stub',
            'complete': False,
            'warning': ('No FMP_API_KEY is set, so these are placeholder '
                        'figures, not market data.'),
            'fundamental': fundamental,
            'valuation': valuation,
            'technical': technical,
            'committee': committee,
        }

    extraction = extract(_fetch(client, ticker))
    fundamental_in, valuation_in, technical_in = split(extraction.metrics)
    fundamental, valuation, technical, committee = _score(
        fundamental_in, valuation_in, technical_in)

    result = {
        'ticker': ticker,
        'data_source': 'live',
        'complete': not extraction.missing,
        'coverage': _coverage(extraction.missing),
        'fundamental': fundamental,
        'valuation': valuation,
        'technical': technical,
        'committee': committee,
    }
    if extraction.missing:
        result['missing_fields'] = sorted(extraction.missing)
        result['warning'] = MISSING_FIELD_WARNING
    return result
