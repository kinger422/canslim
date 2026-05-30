from fastapi import FastAPI
from agents.fundamental import FundamentalAgent
from agents.valuation import ValuationAgent
from agents.technical import TechnicalAgent
from agents.committee import CommitteeAgent

app = FastAPI(title='Apex Equity Research')

@app.get('/')
def health():
    return {'status':'ok','application':'Apex Equity Research'}

@app.get('/analyze/{ticker}')
def analyze(ticker:str):
    fundamental = FundamentalAgent().score({
        'roic':20,
        'revenueGrowth':12,
        'epsGrowth':15,
        'fcfMargin':18,
        'debtToEquity':0.6
    })

    valuation = ValuationAgent().score({
        'peRatio':18,
        'evToEbitda':12,
        'fcfYield':0.045
    })

    technical = TechnicalAgent().score({
        'price':100,
        'sma50':95,
        'sma200':90,
        'rsi':58
    })

    committee = CommitteeAgent().evaluate(
        fundamental['quality_score'],
        valuation['valuation_score'],
        technical['technical_score'],
        25
    )

    return {
        'ticker': ticker.upper(),
        'fundamental': fundamental,
        'valuation': valuation,
        'technical': technical,
        'committee': committee
    }
