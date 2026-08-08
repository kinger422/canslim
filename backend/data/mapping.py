"""Map FMP API payloads onto the dicts the scoring agents expect.

Two hazards this module exists to contain.

**Silent zeros.** The agents default a missing metric to 0 (or 999 for
debt-to-equity), and every one of those defaults scores as a failed
criterion. So a mistyped or renamed remote field does not raise — it
produces a confident SELL on every ticker. `extract` therefore reports
exactly which fields it could not find, so the caller can refuse to
recommend rather than recommend from nothing.

**Percent vs ratio.** The agents mix conventions: `roic > 15` and
`revenueGrowth > 10` are percentages, while `fcfYield > 0.05` and
`debtToEquity < 1` are ratios. FMP returns ratios throughout. Scaling one
group and not the other is invisible in the output and turns every quality
score into a zero, so the factor is declared per field below.

The remote field names carry `candidates` rather than a single string
because FMP renamed several fields when `/stable` superseded `/v3`. The
first candidate present wins, and `resolved` records which one matched.
Run `scripts/verify_fmp_fields.py` against a live key to confirm.
"""

from collections import namedtuple

# scale: multiply the remote value by this to reach the agent's unit.
#        100 converts a ratio (0.20) into a percentage (20).
FieldSpec = namedtuple('FieldSpec', 'key source candidates scale unit')

FIELD_SPECS = (
    # --- FundamentalAgent: thresholds are percentages -------------------
    FieldSpec('roic', 'key_metrics',
              ('returnOnInvestedCapital', 'roic'), 100, 'percent'),
    FieldSpec('revenueGrowth', 'growth',
              ('growthRevenue', 'revenueGrowth'), 100, 'percent'),
    FieldSpec('epsGrowth', 'growth',
              ('growthEPS', 'epsgrowth', 'epsGrowth'), 100, 'percent'),
    FieldSpec('fcfMargin', 'ratios',
              ('freeCashFlowMargin', 'freeCashFlowOperatingCashFlowRatio'), 100, 'percent'),
    FieldSpec('debtToEquity', 'ratios',
              ('debtToEquityRatio', 'debtToEquity'), 1, 'ratio'),

    # --- ValuationAgent --------------------------------------------------
    FieldSpec('peRatio', 'ratios',
              ('priceToEarningsRatio', 'peRatio', 'priceEarningsRatio'), 1, 'multiple'),
    FieldSpec('evToEbitda', 'key_metrics',
              ('evToEBITDA', 'enterpriseValueOverEBITDA'), 1, 'multiple'),
    FieldSpec('fcfYield', 'key_metrics',
              ('freeCashFlowYield',), 1, 'ratio'),

    # --- TechnicalAgent --------------------------------------------------
    FieldSpec('price', 'quote', ('price',), 1, 'currency'),
    FieldSpec('sma50', 'quote', ('priceAvg50',), 1, 'currency'),
    FieldSpec('sma200', 'quote', ('priceAvg200',), 1, 'currency'),
    FieldSpec('rsi', 'rsi', ('rsi',), 1, 'index'),
)

FUNDAMENTAL_KEYS = ('roic', 'revenueGrowth', 'epsGrowth', 'fcfMargin', 'debtToEquity')
VALUATION_KEYS = ('peRatio', 'evToEbitda', 'fcfYield')
TECHNICAL_KEYS = ('price', 'sma50', 'sma200', 'rsi')

Extraction = namedtuple('Extraction', 'metrics missing resolved')


def extract(sources: dict) -> Extraction:
    """Pull agent inputs out of raw FMP payloads.

    `sources` maps a source name ('quote', 'key_metrics', 'ratios',
    'growth', 'rsi') to that endpoint's decoded row.

    Returns the metrics that were found, the agent keys that were not, and
    the remote field name that satisfied each one. A field that is absent
    is *omitted* rather than defaulted, so nothing downstream can mistake
    "not reported" for "reported as zero".
    """
    metrics, missing, resolved = {}, [], {}

    for spec in FIELD_SPECS:
        row = sources.get(spec.source) or {}
        if not isinstance(row, dict):
            missing.append(spec.key)
            continue

        for candidate in spec.candidates:
            value = row.get(candidate)
            if value is None:
                continue
            try:
                metrics[spec.key] = float(value) * spec.scale
            except (TypeError, ValueError):
                continue
            resolved[spec.key] = candidate
            break
        else:
            missing.append(spec.key)

    return Extraction(metrics, missing, resolved)


def split(metrics: dict):
    """Split a flat metrics dict into the three per-agent payloads."""
    def take(keys):
        return {k: metrics[k] for k in keys if k in metrics}
    return take(FUNDAMENTAL_KEYS), take(VALUATION_KEYS), take(TECHNICAL_KEYS)
