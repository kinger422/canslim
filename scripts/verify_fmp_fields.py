#!/usr/bin/env python3
"""Check the FMP field mapping against a live account.

FMP renamed a number of fields when /stable superseded /v3, and the exact
names vary by plan. The mapping in `backend/data/mapping.py` lists candidate
names per metric; this reports which candidate your key actually returns and
which metrics resolve to nothing.

    export FMP_API_KEY=...
    python3 scripts/verify_fmp_fields.py AAPL

Costs five API calls (one per endpoint). Prints the resolved field name for
each metric, then every metric that could not be found, with the candidates
that were tried and a sample of what the endpoint did return — which is
usually enough to spot the current name and add it to FIELD_SPECS.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'backend'))

from analysis import _fetch                                       # noqa: E402
from data.fmp_client import FMPClient, FMPError                   # noqa: E402
from data.mapping import FIELD_SPECS, extract                     # noqa: E402


def main(argv):
    ticker = argv[1] if len(argv) > 1 else 'AAPL'

    client = FMPClient.from_env()
    if client is None:
        print('FMP_API_KEY is not set. Get a free key at '
              'financialmodelingprep.com and export it first.', file=sys.stderr)
        return 2

    try:
        sources = _fetch(client, ticker)
    except FMPError as exc:
        print('could not reach FMP: %s' % exc, file=sys.stderr)
        return 1

    result = extract(sources)

    print('\nFMP field mapping for %s' % ticker.upper())
    print('=' * 62)
    for spec in FIELD_SPECS:
        if spec.key in result.resolved:
            value = result.metrics[spec.key]
            print('  ok      %-14s <- %-34s %.4g' % (
                spec.key, '%s.%s' % (spec.source, result.resolved[spec.key]), value))

    if not result.missing:
        print('\nAll %d metrics resolved. The mapping is correct for this account.'
              % len(FIELD_SPECS))
        return 0

    print('\nMISSING (%d) — these score as failed criteria, which reads as SELL'
          % len(result.missing))
    print('-' * 62)
    for spec in FIELD_SPECS:
        if spec.key not in result.missing:
            continue
        row = sources.get(spec.source) or {}
        print('  %s (from %s)' % (spec.key, spec.source))
        print('    tried:     %s' % ', '.join(spec.candidates))
        if isinstance(row, dict) and row:
            available = sorted(row.keys())
            print('    returned:  %s%s' % (
                ', '.join(available[:12]), ' …' if len(available) > 12 else ''))
        else:
            print('    returned:  nothing — endpoint may need a paid plan')
    print('\nAdd the correct names to FIELD_SPECS in backend/data/mapping.py.')
    print('Mind the unit: roic, revenueGrowth, epsGrowth and fcfMargin are')
    print('compared as percentages, so a ratio needs scale=100.')
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
