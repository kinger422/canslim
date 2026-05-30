class TechnicalAgent:
    def score(self, data: dict):
        score = 0

        price = data.get('price', 0)
        sma50 = data.get('sma50', 0)
        sma200 = data.get('sma200', 0)
        rsi = data.get('rsi', 50)

        if price > sma200:
            score += 40

        if sma50 > sma200:
            score += 30

        if 40 <= rsi <= 70:
            score += 30

        return {
            'technical_score': min(score,100),
            'price': price,
            'sma50': sma50,
            'sma200': sma200,
            'rsi': rsi
        }
