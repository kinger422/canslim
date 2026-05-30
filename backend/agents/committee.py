class CommitteeAgent:
    def evaluate(self, fundamental_score, valuation_score, technical_score=50, risk_score=50):
        buy_votes = 0
        hold_votes = 0
        sell_votes = 0

        for score in [fundamental_score, valuation_score, technical_score]:
            if score >= 70:
                buy_votes += 1
            elif score >= 50:
                hold_votes += 1
            else:
                sell_votes += 1

        recommendation = 'HOLD'
        if buy_votes >= 2:
            recommendation = 'BUY'
        elif sell_votes >= 2:
            recommendation = 'SELL'

        confidence = round((fundamental_score + valuation_score + technical_score) / 3)

        return {
            'buy_votes': buy_votes,
            'hold_votes': hold_votes,
            'sell_votes': sell_votes,
            'recommendation': recommendation,
            'confidence': confidence,
            'risk_score': risk_score
        }
