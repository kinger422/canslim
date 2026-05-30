from fastapi import FastAPI

app = FastAPI(title='Apex Equity Research')

@app.get('/')
def health():
    return {'status':'ok','application':'Apex Equity Research'}

@app.get('/analyze/{ticker}')
def analyze(ticker:str):
    return {
        'ticker': ticker.upper(),
        'quality_score': 85,
        'valuation_score': 78,
        'technical_score': 82,
        'risk_score': 24,
        'recommendation': 'BUY'
    }
