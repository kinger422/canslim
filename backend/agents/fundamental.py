class FundamentalAgent:
    def score(self, metrics: dict):
        score = 0

        roic = metrics.get('roic', 0)
        revenue_growth = metrics.get('revenueGrowth', 0)
        eps_growth = metrics.get('epsGrowth', 0)
        fcf_margin = metrics.get('fcfMargin', 0)
        debt_to_equity = metrics.get('debtToEquity', 999)

        if roic > 15:
            score += 20
        if revenue_growth > 10:
            score += 20
        if eps_growth > 10:
            score += 20
        if fcf_margin > 10:
            score += 20
        if debt_to_equity < 1:
            score += 20

        return {
            'quality_score': score,
            'metrics': metrics
        }
