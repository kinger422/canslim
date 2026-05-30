class ValuationAgent:
    def score(self, metrics: dict):
        score = 0

        pe = metrics.get('peRatio', 999)
        ev_ebitda = metrics.get('evToEbitda', 999)
        fcf_yield = metrics.get('fcfYield', 0)

        if pe < 15:
            score += 35
        elif pe < 25:
            score += 20

        if ev_ebitda < 10:
            score += 35
        elif ev_ebitda < 15:
            score += 20

        if fcf_yield > 0.05:
            score += 30
        elif fcf_yield > 0.03:
            score += 15

        return {
            'valuation_score': min(score,100),
            'metrics': metrics
        }
