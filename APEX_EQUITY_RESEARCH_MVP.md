# Apex Equity Research MVP

## Vision
Institutional-grade AI equity research platform.

## Components
- Stock Screener
- ETF Analyzer
- Fundamental Agent
- Valuation Agent
- Technical Agent
- Risk Agent
- Investment Committee
- PDF Report Generator

## Data Sources
- Financial Modeling Prep
- SEC Filings
- FRED

## Initial API Endpoints
- /analyze/{ticker}
- /etf/{ticker}
- /watchlist
- /committee/{ticker}

## Example Output
Buy/Hold/Sell recommendation with supporting bull and bear cases.

## Running it

```bash
pip install -r requirements.txt
cd backend && uvicorn app:app --reload
```

`backend/app.py` imports its agents as `from agents.x import ...`, so it must
be started from inside `backend/`. Then `curl localhost:8000/analyze/AAPL`.

### Live data

Without a key the service runs on placeholder figures and says so —
`"data_source": "stub"` and a warning on every response. For real data, get a
free key at financialmodelingprep.com and export it:

```bash
export FMP_API_KEY=your-key-here
```

Verify the field mapping against your account before trusting any output:

```bash
python3 scripts/verify_fmp_fields.py AAPL
```

FMP renamed a number of fields when `/stable` superseded `/v3`, and coverage
varies by plan, so `backend/data/mapping.py` lists candidate names per metric.
The script reports which candidate your key actually returns and what to add
for anything that resolves to nothing.

**Why that check matters.** The agents treat an absent metric as a failed
criterion, so an unmapped field does not raise — it scores zero and reads as a
confident SELL. The service therefore reports `complete`, `coverage` and
`missing_fields` on every response; treat a response with `"complete": false`
as diagnostic output, not as a recommendation.

Also mind the units: `roic`, `revenueGrowth`, `epsGrowth` and `fcfMargin` are
compared as percentages while `fcfYield` and `debtToEquity` are compared as
ratios. FMP reports ratios throughout, so the percentage group carries
`scale=100` in the mapping.

### Cost

One analysis costs five API calls (quote, key-metrics, ratios, financial-growth,
RSI). The free tier allows 250 requests/day, so roughly 50 tickers before the
quota is spent.

## Status

Built: the four scoring agents, the committee vote, and the FMP integration
behind `/analyze/{ticker}`. Not built: the Risk Agent (the committee accepts a
`risk_score` and passes it through, but does not vote on it), the screener,
`/etf/{ticker}`, `/watchlist`, `/committee/{ticker}`, and the PDF generator.
