"""5%-of-free-balance position sizing for a Kalshi contract.

Kalshi contracts have no leverage: buying N contracts at price P (cents) risks at most
N * P cents (they can go to 0). So "risk 5% of free balance" translates directly into
a contract-count cap, no separate stop-distance math needed for sizing itself
(the stop/target logic in stop_target.py is about *when to exit*, not how much to risk).
"""

RISK_FRACTION = 0.05


def max_contracts(free_balance_cents: int, entry_price_cents: int, risk_fraction: float = RISK_FRACTION) -> int:
    if entry_price_cents <= 0:
        raise ValueError("entry_price_cents must be > 0")
    risk_budget_cents = free_balance_cents * risk_fraction
    return int(risk_budget_cents // entry_price_cents)


def size_trade(free_balance_cents: int, entry_price_cents: int, risk_fraction: float = RISK_FRACTION) -> dict:
    count = max_contracts(free_balance_cents, entry_price_cents, risk_fraction)
    cost_cents = count * entry_price_cents
    return {
        "contracts": count,
        "cost_cents": cost_cents,
        "risk_budget_cents": round(free_balance_cents * risk_fraction),
        "max_loss_cents": cost_cents,  # full loss if contract expires worthless
        "free_balance_cents": free_balance_cents,
    }


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Compute a 5%-of-free-balance contract count.")
    p.add_argument("free_balance_cents", type=int)
    p.add_argument("entry_price_cents", type=int)
    p.add_argument("--risk-fraction", type=float, default=RISK_FRACTION)
    args = p.parse_args()
    result = size_trade(args.free_balance_cents, args.entry_price_cents, args.risk_fraction)
    for k, v in result.items():
        print(f"{k}: {v}")
