"""Orchestrates one 5%-risk, 15-minute directional Kalshi trade end to end:

  size -> enter -> poll market, adapt stop/target -> exit

Usage:
  python run_trade.py TICKER SIDE [--demo] [--window-seconds 900] [--poll-seconds 3] [--dry-run]

  TICKER      Kalshi market ticker, e.g. "KXUSDJPY-25JUL26-T150"
  SIDE        "yes" or "no" -- the direction you believe wins

--dry-run prints every decision without placing real orders (recommended for a first pass
even against --demo, since it also verifies the sizing/stop/target math before any order fires).
"""
import argparse
import time
import sys

from kalshi_client import KalshiClient
from position_sizer import size_trade
from stop_target import TradeState, StopTargetConfig


def main():
    p = argparse.ArgumentParser()
    p.add_argument("ticker")
    p.add_argument("side", choices=["yes", "no"])
    p.add_argument("--demo", action="store_true", help="use Kalshi's sandbox instead of production")
    p.add_argument("--window-seconds", type=float, default=900.0)
    p.add_argument("--poll-seconds", type=float, default=3.0)
    p.add_argument("--dry-run", action="store_true", help="compute and log decisions, place no orders")
    p.add_argument("--risk-fraction", type=float, default=0.05)
    args = p.parse_args()

    client = KalshiClient(demo=args.demo)

    balance = client.balance_cents()
    market = client.get_market(args.ticker)
    entry_price = market["yes_ask"] if args.side == "yes" else market["no_ask"]

    sizing = size_trade(balance, entry_price, args.risk_fraction)
    print(f"[size] balance={balance}c risk_fraction={args.risk_fraction} -> {sizing}")

    if sizing["contracts"] <= 0:
        print("Free balance too small for even 1 contract at 5% risk. Aborting.")
        sys.exit(1)

    client_order_id = f"5pct-{args.ticker}-{int(time.time())}"
    if args.dry_run:
        print(f"[dry-run] would BUY {sizing['contracts']} {args.side} @ {entry_price}c on {args.ticker}")
    else:
        resp = client.place_order(
            args.ticker, args.side, "buy", sizing["contracts"], entry_price, client_order_id
        )
        print(f"[order] entry placed: {resp}")

    state = TradeState(
        side=args.side,
        entry_price=entry_price,
        window_seconds=args.window_seconds,
        started_at=time.time(),
        config=StopTargetConfig(),
    )

    print("[monitor] polling for stop/target/expiry...")
    while True:
        time.sleep(args.poll_seconds)
        market = client.get_market(args.ticker)
        price = market["yes_bid"] if args.side == "yes" else market["no_bid"]
        result = state.update(time.time(), price)
        print(f"[tick] price={price}c -> {result}")

        if result["action"] == "exit":
            print(f"[exit] reason={result['reason']} price={result.get('price')}")
            if args.dry_run:
                print(f"[dry-run] would SELL {sizing['contracts']} {args.side} @ {price}c")
            else:
                exit_order_id = f"{client_order_id}-exit"
                resp = client.place_order(
                    args.ticker, args.side, "sell", sizing["contracts"], price, exit_order_id
                )
                print(f"[order] exit placed: {resp}")
            break


if __name__ == "__main__":
    main()
