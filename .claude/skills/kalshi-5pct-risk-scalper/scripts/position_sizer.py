"""5%-of-free-balance position sizing for a Kalshi contract, fee-aware.

Kalshi contracts have no leverage: buying N contracts at price P (cents) risks at most
N * P cents plus taker fees. Kalshi's taker fee is approximately
ceil(0.07 * count * price * (1 - price)) per fill (price as a probability), charged on
the entry buy and again on an early exit sell — so sizing must budget for both, or the
real cash at risk quietly exceeds the advertised 5% cap on essentially every trade.
"""
import math

RISK_FRACTION = 0.05


def taker_fee_cents(count: int, price_cents: int) -> int:
    p = price_cents / 100.0
    return math.ceil(0.07 * count * p * (1 - p) * 100)


def total_debit_cents(count: int, price_cents: int) -> int:
    """Worst-case cash outlay: premium + entry fee + a reserved exit fee."""
    return count * price_cents + 2 * taker_fee_cents(count, price_cents)


def max_contracts(free_balance_cents: int, entry_price_cents: int, risk_fraction: float = RISK_FRACTION) -> int:
    if entry_price_cents <= 0 or entry_price_cents >= 100:
        raise ValueError("entry_price_cents must be in 1..99")
    if not (0 < risk_fraction <= 1.0):
        raise ValueError("risk_fraction must be in (0, 1]")
    risk_budget_cents = free_balance_cents * risk_fraction
    count = int(risk_budget_cents // entry_price_cents)
    while count > 0 and total_debit_cents(count, entry_price_cents) > risk_budget_cents:
        count -= 1
    return count


def size_trade(free_balance_cents: int, entry_price_cents: int, risk_fraction: float = RISK_FRACTION) -> dict:
    count = max_contracts(free_balance_cents, entry_price_cents, risk_fraction)
    cost_cents = count * entry_price_cents
    fee = taker_fee_cents(count, entry_price_cents)
    return {
        "contracts": count,
        "cost_cents": cost_cents,
        "entry_fee_cents": fee,
        "reserved_exit_fee_cents": fee,
        "risk_budget_cents": round(free_balance_cents * risk_fraction),
        "max_loss_cents": cost_cents + 2 * fee,  # full premium loss + both taker fees
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
