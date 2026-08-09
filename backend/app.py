from fastapi import FastAPI, HTTPException

from analysis import build_analysis
from data.fmp_client import FMPClient, FMPError

app = FastAPI(title='Apex Equity Research')


@app.get('/')
def health():
    return {
        'status': 'ok',
        'application': 'Apex Equity Research',
        'data_source': 'live' if FMPClient.from_env() else 'stub',
    }


@app.get('/analyze/{ticker}')
def analyze(ticker: str):
    try:
        return build_analysis(ticker, client=FMPClient.from_env())
    except FMPError as exc:
        # An upstream outage is a 502, not a quiet fallback to placeholders.
        raise HTTPException(status_code=502, detail=str(exc)) from exc
